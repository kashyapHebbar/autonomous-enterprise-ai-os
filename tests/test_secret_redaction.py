from __future__ import annotations

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.archive import REDACTED
from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord
from aeai_os.runs.repository import InMemoryRunRepository, utc_now
from aeai_os.schemas.enums import AgentEventType, ArtifactType, WorkflowJobStatus
from aeai_os.security.redaction import redact_text, redact_uri, redact_value
from aeai_os.settings import get_env_secret


def test_redaction_scrubs_secret_keys_and_uri_credentials():
    payload = {
        "credential_profile_id": "snowflake-default",
        "password": "hunter2",
        "nested": {"api_token": "token-123"},
        "uri": "s3://user:pass@bucket/raw.csv?token=abc&region=us",
        "message": "call failed with password=hunter2 and Bearer abc123",
    }

    redacted = redact_value(payload)

    assert redacted["credential_profile_id"] == "snowflake-default"
    assert redacted["password"] == REDACTED
    assert redacted["nested"]["api_token"] == REDACTED
    assert "pass" not in redacted["uri"]
    assert "token=%5BREDACTED%5D" in redacted["uri"]
    assert "hunter2" not in redacted["message"]
    assert "abc123" not in redacted["message"]
    assert redact_uri("postgres://user:pw@db/app?ssl=true") == (
        "postgres://[REDACTED]@db/app?ssl=true"
    )
    assert redact_text("api_key=secret-value") == f"api_key={REDACTED}"


def test_env_secret_loader_supports_file_convention_and_direct_precedence(tmp_path):
    secret_file = tmp_path / "database-url"
    secret_file.write_text("postgresql://user:file-secret@db/app\n", encoding="utf-8")
    env = {
        "AEAI_DATABASE_URL_FILE": str(secret_file),
        "AEAI_AUTH_TOKEN_PROFILES": "direct-token=admin|Admin|admin",
        "AEAI_AUTH_TOKEN_PROFILES_FILE": str(secret_file),
    }

    assert get_env_secret("AEAI_DATABASE_URL", env=env) == (
        "postgresql://user:file-secret@db/app"
    )
    assert get_env_secret("AEAI_AUTH_TOKEN_PROFILES", env=env) == (
        "direct-token=admin|Admin|admin"
    )


def test_live_run_api_responses_redact_secret_like_values(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run(
        "Analyze data with password=hunter2.",
        metadata={
            "api_token": "run-secret",
            "credential_profile_id": "snowflake-default",
        },
    )
    artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://user:artifact-password@bucket/raw.csv?token=artifact-token",
        metadata={
            "password": "metadata-secret",
            "credential_profile_id": "snowflake-default",
        },
    )
    repository.add_event(
        AgentEventRecord(
            id="event_secret",
            run_id=run.id,
            node_id="data",
            event_type=AgentEventType.LOG.value,
            payload={"message": "token=event-secret", "access_token": "event-token"},
            created_at=utc_now(),
        )
    )
    repository.add_evaluation(
        EvaluationResultRecord(
            id="eval_secret",
            run_id=run.id,
            score=1.0,
            passed=True,
            checks=[{"name": "quality", "secret": "eval-secret"}],
        )
    )
    repository.enqueue_workflow_job(
        run_id=run.id,
        workflow_name="procurement",
        payload={"api_key": "job-secret"},
        status=WorkflowJobStatus.COMPLETED,
    )
    repository.save_checkpoint(run.id, {"auth_token": "checkpoint-secret"})
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))

    run_body = client.get(f"/runs/{run.id}").json()
    events_body = client.get(f"/runs/{run.id}/events").json()
    jobs_body = client.get(f"/runs/{run.id}/workflow-jobs").json()
    timeline_body = client.get(f"/runs/{run.id}/timeline").json()
    archive_body = client.get(f"/runs/{run.id}/export").json()
    combined = str([run_body, events_body, jobs_body, timeline_body, archive_body])

    assert "hunter2" not in combined
    assert "run-secret" not in combined
    assert "artifact-password" not in combined
    assert "artifact-token" not in combined
    assert "metadata-secret" not in combined
    assert "event-secret" not in combined
    assert "event-token" not in combined
    assert "eval-secret" not in combined
    assert "job-secret" not in combined
    assert "checkpoint-secret" not in combined
    assert run_body["metadata"]["credential_profile_id"] == "snowflake-default"
    assert run_body["artifacts"][0]["metadata"]["credential_profile_id"] == (
        "snowflake-default"
    )
    assert run_body["artifacts"][0]["id"] == artifact.id
    assert archive_body["checkpoint"]["state"]["auth_token"] == REDACTED

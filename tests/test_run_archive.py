from __future__ import annotations

import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.runs.archive import (
    REDACTED,
    RunArchiveConflictError,
    export_run_archive,
    import_run_archive,
)
from aeai_os.runs.models import (
    AgentEventRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
)
from aeai_os.runs.repository import InMemoryRunRepository, utc_now
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.schemas.enums import (
    AgentEventType,
    ArtifactType,
    GraphNodeStatus,
    RunStatus,
    WorkflowJobStatus,
)


def seed_archivable_run(repository):
    run = repository.create_run(
        "Analyze procurement data.",
        metadata={"tenant": "demo", "api_token": "super-secret"},
        trace_id="trace_archive_demo",
    )
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://user:password@bucket/raw/procurement.csv?token=abc",
        metadata={
            "source": "warehouse",
            "password": "dont-export",
            "storage_backend": "s3",
            "storage_key": "raw/procurement.csv",
            "content_type": "text/csv",
            "size_bytes": 100,
        },
    )
    dashboard = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DASHBOARD,
        uri="s3://bucket/dashboard/procurement.html",
        metadata={"storage_backend": "s3", "storage_key": "dashboard/procurement.html"},
        source_artifact_ids=[dataset.id],
        producer_node_id="visualization",
        content_type="text/html",
        size_bytes=1000,
    )
    report = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri="s3://bucket/report/procurement.md",
        metadata={"storage_backend": "s3", "storage_key": "report/procurement.md"},
        source_artifact_ids=[dataset.id, dashboard.id],
        producer_node_id="report",
        content_type="text/markdown",
        size_bytes=500,
    )
    created_at = utc_now()
    repository.upsert_graph_node(
        GraphNodeRecord(
            id="visualization",
            run_id=run.id,
            agent_type="visualization",
            status=GraphNodeStatus.COMPLETED,
            depends_on=["analytics"],
            required_tools=["chart_renderer"],
            expected_artifacts=["dashboard"],
            retry_count=0,
            created_at=created_at,
            updated_at=created_at,
            started_at=created_at,
            finished_at=created_at,
        )
    )
    repository.add_event(
        AgentEventRecord(
            id="event_dashboard",
            run_id=run.id,
            node_id="visualization",
            event_type=AgentEventType.LOG.value,
            payload={"message": "dashboard created", "access_token": "dont-export"},
            created_at=created_at,
        )
    )
    repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_dashboard",
            run_id=run.id,
            target_artifact_id=dashboard.id,
            score=1.0,
            passed=True,
            checks=[{"name": "dashboard", "passed": True, "secret": "dont-export"}],
            created_at=created_at,
        )
    )
    repository.enqueue_workflow_job(
        run_id=run.id,
        workflow_name="procurement",
        payload={"mode": "demo", "api_key": "dont-export"},
        status=WorkflowJobStatus.COMPLETED,
    )
    repository.save_checkpoint(
        run.id,
        {
            "run_id": run.id,
            "artifacts": {"visualization": [dashboard.id]},
            "auth_token": "dont-export",
        },
    )
    repository.update_status(run.id, RunStatus.COMPLETED)
    return repository.get_run(run.id), dataset, dashboard, report


def test_run_archive_exports_sanitized_state_and_imports_for_lineage():
    source_repository = InMemoryRunRepository()
    run, dataset, dashboard, report = seed_archivable_run(source_repository)

    archive = export_run_archive(source_repository, run.id)
    target_repository = InMemoryRunRepository()
    imported = import_run_archive(target_repository, archive)
    lineage = ArtifactLineageService(target_repository).build_lineage(run.id, report.id)
    edge_pairs = {
        (edge.source_artifact_id, edge.target_artifact_id)
        for edge in lineage.edges
    }

    assert archive["schema_version"] == "aeai.run_archive.v1"
    assert archive["run"]["metadata"]["api_token"] == REDACTED
    assert archive["artifacts"][0]["metadata"]["password"] == REDACTED
    assert "password" not in archive["artifacts"][0]["uri"]
    assert "token=%5BREDACTED%5D" in archive["artifacts"][0]["uri"]
    assert archive["events"][0]["payload"]["access_token"] == REDACTED
    assert archive["evaluations"][0]["checks"][0]["secret"] == REDACTED
    assert archive["workflow_jobs"][0]["payload"]["api_key"] == REDACTED
    assert archive["checkpoint"]["state"]["auth_token"] == REDACTED
    assert imported.id == run.id
    assert target_repository.get_run(run.id).status == RunStatus.COMPLETED
    assert target_repository.get_artifact(run.id, dashboard.id).storage_backend == "s3"
    assert {dataset.id, dashboard.id} <= {
        artifact.id for artifact in lineage.upstream_artifacts
    }
    assert (dashboard.id, report.id) in edge_pairs


def test_run_archive_import_rejects_duplicate_without_overwrite():
    repository = InMemoryRunRepository()
    run, *_ = seed_archivable_run(repository)
    archive = export_run_archive(repository, run.id)

    with pytest.raises(RunArchiveConflictError):
        import_run_archive(repository, archive)

    imported = import_run_archive(repository, archive, overwrite=True)

    assert imported.id == run.id


def test_api_imported_archive_is_visible_to_run_inspector(tmp_path):
    source_repository = InMemoryRunRepository()
    run, dataset, dashboard, report = seed_archivable_run(source_repository)
    source_app = create_app(repository=source_repository, artifact_root=tmp_path / "source")
    source_client = TestClient(source_app)
    export_response = source_client.get(f"/runs/{run.id}/export")
    archive = export_response.json()
    target_repository = InMemoryRunRepository()
    app = create_app(repository=target_repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)

    import_response = client.post("/runs/import", json={"archive": archive})
    run_response = client.get(f"/runs/{run.id}")
    timeline_response = client.get(f"/runs/{run.id}/timeline")
    lineage_response = client.get(f"/runs/{run.id}/artifacts/{report.id}/lineage")

    assert export_response.status_code == 200
    assert export_response.json()["run"]["id"] == run.id
    assert import_response.status_code == 201
    assert run_response.status_code == 200
    assert run_response.json()["id"] == run.id
    assert timeline_response.status_code == 200
    assert {item["kind"] for item in timeline_response.json()} >= {
        "run",
        "artifact",
        "agent_event",
        "evaluation",
    }
    assert lineage_response.status_code == 200
    upstream_ids = {
        artifact["id"] for artifact in lineage_response.json()["upstream_artifacts"]
    }
    assert {dataset.id, dashboard.id} <= upstream_ids


def test_run_archive_cli_exports_and_replays_sqlalchemy_run(tmp_path):
    source_url = f"sqlite+pysqlite:///{tmp_path / 'source.db'}"
    target_url = f"sqlite+pysqlite:///{tmp_path / 'target.db'}"
    source_repository = SQLAlchemyRunRepository.from_url(source_url, create_schema=True)
    run, _, _, report = seed_archivable_run(source_repository)
    archive_path = tmp_path / "run-archive.json"

    export_result = subprocess.run(
        [
            sys.executable,
            "scripts/manage_run_archive.py",
            "--database-url",
            source_url,
            "export",
            run.id,
            "--output",
            str(archive_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    import_result = subprocess.run(
        [
            sys.executable,
            "scripts/manage_run_archive.py",
            "--database-url",
            target_url,
            "--create-schema",
            "replay",
            "--input",
            str(archive_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    target_repository = SQLAlchemyRunRepository.from_url(target_url, create_schema=False)

    assert export_result.returncode == 0, export_result.stderr
    assert import_result.returncode == 0, import_result.stderr
    assert archive_path.exists()
    assert json.loads(archive_path.read_text(encoding="utf-8"))["run"]["id"] == run.id
    assert target_repository.get_run(run.id).status == RunStatus.COMPLETED
    assert target_repository.get_artifact(run.id, report.id).type == ArtifactType.REPORT

from __future__ import annotations

import sys
from datetime import UTC, datetime

from aeai_os.observability import (
    LangSmithTrackingConfig,
    build_langsmith_tracker,
    build_langsmith_tracking_config,
)
from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord, RunRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, RunStatus


class FakeLangSmithClient:
    def __init__(self) -> None:
        self.init_kwargs = {}
        self.created_runs = []
        self.updated_runs = []

    def create_run(self, **kwargs):
        self.created_runs.append(kwargs)

    def update_run(self, run_id, **kwargs):
        self.updated_runs.append({"run_id": run_id, **kwargs})


class FakeLangSmithModule:
    def __init__(self, client: FakeLangSmithClient) -> None:
        self.client = client

    def Client(self, **kwargs):  # noqa: N802 - mirrors the langsmith SDK API.
        self.client.init_kwargs = kwargs
        return self.client


def _run_record() -> RunRecord:
    return RunRecord(
        id="run_123",
        task="Analyze procurement data.",
        status=RunStatus.RUNNING,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        trace_id="trace_123",
    )


def test_langsmith_tracking_config_defaults_to_disabled():
    config = build_langsmith_tracking_config(env={})
    tracker = build_langsmith_tracker(config)

    assert config.enabled is False
    assert tracker.status == "disabled"


def test_langsmith_tracking_config_reads_aeai_env_values():
    config = build_langsmith_tracking_config(
        env={
            "AEAI_LANGSMITH_TRACING_ENABLED": "true",
            "AEAI_LANGSMITH_API_KEY": "test-key",
            "AEAI_LANGSMITH_ENDPOINT": "https://langsmith.example.test",
            "AEAI_LANGSMITH_PROJECT": "AEAI Trace Review",
            "AEAI_LANGSMITH_RUN_NAME_PREFIX": "trace-review",
            "AEAI_LANGSMITH_TAGS": "team=platform,env=test",
        }
    )

    assert config.enabled is True
    assert config.api_key == "test-key"
    assert config.endpoint == "https://langsmith.example.test"
    assert config.project_name == "AEAI Trace Review"
    assert config.run_name_prefix == "trace-review"
    assert config.tags == {"team": "platform", "env": "test"}


def test_langsmith_tracking_reports_missing_api_key_without_importing_package():
    config = build_langsmith_tracking_config(
        env={"AEAI_LANGSMITH_TRACING_ENABLED": "true"}
    )
    tracker = build_langsmith_tracker(
        config,
        importer=lambda name: (_ for _ in ()).throw(AssertionError(name)),
    )

    assert tracker.status == "not_configured"
    assert "AEAI_LANGSMITH_API_KEY" in tracker.message


def test_langsmith_tracking_reports_unavailable_when_package_is_missing():
    config = build_langsmith_tracking_config(
        env={
            "AEAI_LANGSMITH_TRACING_ENABLED": "true",
            "AEAI_LANGSMITH_API_KEY": "test-key",
        }
    )
    tracker = build_langsmith_tracker(
        config,
        importer=lambda name: (_ for _ in ()).throw(ImportError(name)),
    )

    assert tracker.status == "unavailable"
    assert "optional langsmith package" in tracker.message


def test_langsmith_tracker_logs_agent_event_with_review_metadata():
    fake_client = FakeLangSmithClient()
    config = LangSmithTrackingConfig(
        enabled=True,
        api_key="test-key",
        endpoint="https://langsmith.example.test",
        project_name="AEAI Trace Review",
        run_name_prefix="trace-review",
        tags={"team": "platform"},
    )
    event = AgentEventRecord(
        id="event_profile_complete",
        run_id="run_123",
        node_id="profile",
        event_type=AgentEventType.LOG.value,
        payload={
            "agent": "data_retrieval",
            "message": "profile complete",
            "artifacts": ["artifact_profile"],
            "source_artifact_ids": ["artifact_dataset"],
        },
        created_at=datetime.now(UTC),
    )

    result = build_langsmith_tracker(config, client=fake_client).log_agent_event(
        run=_run_record(),
        event=event,
    )

    assert result.status == "logged"
    created = fake_client.created_runs[0]
    assert created["project_name"] == "AEAI Trace Review"
    assert created["inputs"] == {
        "task": "Analyze procurement data.",
        "event_type": "log",
        "node_id": "profile",
    }
    assert created["metadata"]["aeai.run_id"] == "run_123"
    assert created["metadata"]["aeai.trace_id"] == "trace_123"
    assert created["metadata"]["aeai.graph_node_id"] == "profile"
    assert created["metadata"]["aeai.agent_name"] == "data_retrieval"
    assert created["metadata"]["aeai.artifact_ids"] == [
        "artifact_dataset",
        "artifact_profile",
    ]
    assert "team:platform" in created["tags"]
    assert fake_client.updated_runs[0]["outputs"]["payload"]["message"] == "profile complete"


def test_langsmith_tracker_logs_evaluation_with_artifact_metadata():
    fake_client = FakeLangSmithClient()
    config = LangSmithTrackingConfig(enabled=True, api_key="test-key")
    evaluation = EvaluationResultRecord(
        id="evaluation_profile",
        run_id="run_123",
        score=0.9,
        passed=True,
        checks=[{"name": "profile", "score": 0.9, "passed": True}],
        created_at=datetime.now(UTC),
        target_artifact_id="artifact_report",
    )

    result = build_langsmith_tracker(config, client=fake_client).log_evaluation(
        run=_run_record(),
        evaluation=evaluation,
    )

    created = fake_client.created_runs[0]
    assert result.status == "logged"
    assert created["metadata"]["aeai.evaluation_id"] == "evaluation_profile"
    assert created["metadata"]["aeai.target_artifact_id"] == "artifact_report"
    assert created["metadata"]["aeai.artifact_ids"] == ["artifact_report"]
    assert fake_client.updated_runs[0]["outputs"]["score"] == 0.9


def test_repository_agent_events_emit_langsmith_metadata_when_enabled(monkeypatch):
    fake_client = FakeLangSmithClient()
    monkeypatch.setitem(sys.modules, "langsmith", FakeLangSmithModule(fake_client))
    monkeypatch.setenv("AEAI_LANGSMITH_TRACING_ENABLED", "true")
    monkeypatch.setenv("AEAI_LANGSMITH_API_KEY", "test-key")
    monkeypatch.setenv("AEAI_LANGSMITH_PROJECT", "AEAI Repository Tests")

    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    repository.add_event(
        AgentEventRecord(
            id="event_profile_complete",
            run_id=run.id,
            node_id="profile",
            event_type=AgentEventType.LOG.value,
            payload={
                "agent": "data_retrieval",
                "message": "profile complete",
                "artifacts": ["artifact_profile"],
            },
            created_at=datetime.now(UTC),
        )
    )

    created = fake_client.created_runs[0]
    assert fake_client.init_kwargs == {"api_key": "test-key"}
    assert created["project_name"] == "AEAI Repository Tests"
    assert created["metadata"]["aeai.run_id"] == run.id
    assert created["metadata"]["aeai.graph_node_id"] == "profile"
    assert created["metadata"]["aeai.agent_name"] == "data_retrieval"
    assert created["metadata"]["aeai.artifact_ids"] == ["artifact_profile"]

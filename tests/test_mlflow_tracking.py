from __future__ import annotations

import sys
from datetime import UTC, datetime

from aeai_os.observability import (
    MLflowTrackingConfig,
    build_mlflow_tracker,
    build_mlflow_tracking_config,
)
from aeai_os.runs.models import EvaluationResultRecord, RunRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, RunStatus


class FakeMLflowRun:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeMLflowClient:
    def __init__(self) -> None:
        self.tracking_uri = None
        self.experiment_name = None
        self.started_runs = []
        self.params = {}
        self.metrics = {}

    def set_tracking_uri(self, tracking_uri: str) -> None:
        self.tracking_uri = tracking_uri

    def set_experiment(self, experiment_name: str) -> None:
        self.experiment_name = experiment_name

    def start_run(self, *, run_name: str, tags: dict[str, str]) -> FakeMLflowRun:
        self.started_runs.append({"run_name": run_name, "tags": tags})
        return FakeMLflowRun()

    def log_params(self, params: dict[str, str]) -> None:
        self.params.update(params)

    def log_metrics(self, metrics: dict[str, float]) -> None:
        self.metrics.update(metrics)


def test_mlflow_tracking_config_defaults_to_disabled():
    config = build_mlflow_tracking_config(env={})
    tracker = build_mlflow_tracker(config)

    assert config.enabled is False
    assert tracker.status == "disabled"


def test_mlflow_tracking_reports_unavailable_when_package_is_missing():
    config = build_mlflow_tracking_config(
        env={"AEAI_MLFLOW_TRACKING_ENABLED": "true"}
    )
    tracker = build_mlflow_tracker(
        config,
        importer=lambda name: (_ for _ in ()).throw(ImportError(name)),
    )

    assert tracker.status == "unavailable"
    assert "optional mlflow package" in tracker.message


def test_mlflow_tracker_logs_evaluation_with_fake_client():
    fake_mlflow = FakeMLflowClient()
    config = MLflowTrackingConfig(
        enabled=True,
        tracking_uri="file:./artifacts/mlruns",
        experiment_name="AEAI Tests",
        run_name_prefix="test-run",
        tags={"team": "platform"},
    )
    run = RunRecord(
        id="run_123",
        task="Analyze procurement data.",
        status=RunStatus.COMPLETED,
        metadata={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        trace_id="trace_123",
    )
    evaluation = EvaluationResultRecord(
        id="evaluation_123",
        run_id=run.id,
        score=0.75,
        passed=False,
        checks=[
            {"name": "data consistency", "score": 0.5, "passed": False},
            {"name": "artifact_completeness", "score": 1.0, "passed": True},
        ],
        target_artifact_id="artifact_report",
    )

    result = build_mlflow_tracker(config, mlflow_module=fake_mlflow).log_evaluation(
        run=run,
        evaluation=evaluation,
    )

    assert result.status == "logged"
    assert fake_mlflow.tracking_uri == "file:./artifacts/mlruns"
    assert fake_mlflow.experiment_name == "AEAI Tests"
    assert fake_mlflow.started_runs == [
        {
            "run_name": "test-run-run_123",
            "tags": {
                "team": "platform",
                "aeai.run_id": "run_123",
                "aeai.trace_id": "trace_123",
                "aeai.evaluation_id": "evaluation_123",
            },
        }
    ]
    assert fake_mlflow.params["aeai.run_id"] == "run_123"
    assert fake_mlflow.params["aeai.target_artifact_id"] == "artifact_report"
    assert fake_mlflow.metrics["evaluation_score"] == 0.75
    assert fake_mlflow.metrics["evaluation_passed"] == 0.0
    assert fake_mlflow.metrics["evaluation_check_data_consistency_passed"] == 0.0
    assert fake_mlflow.metrics["evaluation_check_artifact_completeness_score"] == 1.0


def test_repository_evaluation_event_records_disabled_mlflow_status():
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")

    repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_profile",
            run_id=run.id,
            score=1.0,
            passed=True,
            checks=[{"name": "profile", "score": 1.0, "passed": True}],
        )
    )

    evaluation_event = next(
        event
        for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.EVALUATION
    )
    assert evaluation_event.payload["backend"] == "opentelemetry"
    assert evaluation_event.payload["mlflow_status"] == "disabled"
    assert evaluation_event.payload["langsmith_status"] == "disabled"


def test_repository_evaluation_logs_to_mlflow_when_enabled(monkeypatch):
    fake_mlflow = FakeMLflowClient()
    monkeypatch.setitem(sys.modules, "mlflow", fake_mlflow)
    monkeypatch.setenv("AEAI_MLFLOW_TRACKING_ENABLED", "true")
    monkeypatch.setenv("AEAI_MLFLOW_TRACKING_URI", "file:./artifacts/mlruns")
    monkeypatch.setenv("AEAI_MLFLOW_EXPERIMENT_NAME", "AEAI Repository Tests")

    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_profile",
            run_id=run.id,
            score=0.8,
            passed=True,
            checks=[{"name": "data_consistency", "score": 0.8, "passed": True}],
            target_artifact_id="artifact_report",
        )
    )

    evaluation_event = next(
        event
        for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.EVALUATION
    )
    assert evaluation_event.payload["mlflow_status"] == "logged"
    assert evaluation_event.payload["langsmith_status"] == "disabled"
    assert fake_mlflow.tracking_uri == "file:./artifacts/mlruns"
    assert fake_mlflow.experiment_name == "AEAI Repository Tests"
    assert fake_mlflow.params["aeai.run_id"] == run.id
    assert fake_mlflow.metrics["evaluation_score"] == 0.8
    assert fake_mlflow.metrics["evaluation_check_data_consistency_score"] == 0.8

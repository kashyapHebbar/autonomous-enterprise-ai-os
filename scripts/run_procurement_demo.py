# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.agents.evaluation import EvaluationAgent
from aeai_os.agents.planner import PlannerAgent
from aeai_os.agents.registry import build_default_registry
from aeai_os.agents.report import ReportAgent
from aeai_os.agents.visualization import VisualizationAgent
from aeai_os.observability.metrics import render_prometheus_metrics
from aeai_os.orchestration.service import OrchestratorService
from aeai_os.runs.models import ArtifactRecord, EvaluationResultRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType, RunStatus

DEFAULT_TASK = "Analyze this procurement dataset and create a dashboard report."
DEFAULT_DATASET_PATH = ROOT / "examples" / "procurement_demo.csv"
DEFAULT_ARTIFACT_ROOT = ROOT / "artifacts" / "procurement_demo"


@dataclass(frozen=True)
class ProcurementDemoResult:
    run_id: str
    status: RunStatus
    trace_id: str
    artifact_root: Path
    summary_path: Path
    metrics_path: Path
    artifacts: list[dict[str, Any]]
    evaluations: list[dict[str, Any]]
    event_count: int


def run_demo(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT,
    task: str = DEFAULT_TASK,
) -> ProcurementDemoResult:
    dataset_path = dataset_path.resolve()
    artifact_root = artifact_root.resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(f"Demo dataset not found: {dataset_path}")

    repository = InMemoryRunRepository()
    run = repository.create_run(task)
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(dataset_path),
        metadata={
            "source": "procurement_demo",
            "format": "csv",
            "description": "Sample procurement spend dataset for the local MVP demo.",
        },
    )

    plan = PlannerAgent().create_plan(
        run_id=run.id,
        user_task=task,
        dataset_artifact_id=dataset.id,
    )
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={
            "data_retrieval": DataRetrievalAgent(repository, artifact_root),
            "analytics_code": AnalyticsCodeAgent(repository, artifact_root),
            "visualization": VisualizationAgent(repository, artifact_root),
            "report": ReportAgent(repository, artifact_root),
            "evaluation": EvaluationAgent(repository, artifact_root),
        },
    )
    result = service.execute_run(run.id, plan.to_execution_graph())
    refreshed_run = repository.get_run(run.id)
    run_artifact_dir = artifact_root / run.id
    run_artifact_dir.mkdir(parents=True, exist_ok=True)

    artifacts = [_artifact_summary(artifact) for artifact in repository.list_artifacts(run.id)]
    evaluations = [
        _evaluation_summary(evaluation) for evaluation in repository.list_evaluations(run.id)
    ]
    metrics = render_prometheus_metrics(repository)
    metrics_path = run_artifact_dir / "metrics.prom"
    summary_path = run_artifact_dir / "demo_summary.json"
    metrics_path.write_text(metrics, encoding="utf-8")
    summary_payload = {
        "run": {
            "id": refreshed_run.id,
            "status": refreshed_run.status.value,
            "trace_id": refreshed_run.trace_id,
            "task": refreshed_run.task,
            "created_at": refreshed_run.created_at.isoformat(),
            "updated_at": refreshed_run.updated_at.isoformat(),
        },
        "dataset": str(dataset_path),
        "artifact_root": str(artifact_root),
        "artifacts": artifacts,
        "evaluations": evaluations,
        "event_count": len(repository.list_events(run.id)),
        "metrics_path": str(metrics_path),
    }
    summary_path.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    return ProcurementDemoResult(
        run_id=refreshed_run.id,
        status=result.status,
        trace_id=refreshed_run.trace_id or "",
        artifact_root=artifact_root,
        summary_path=summary_path,
        metrics_path=metrics_path,
        artifacts=artifacts,
        evaluations=evaluations,
        event_count=len(repository.list_events(run.id)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the procurement analytics MVP demo.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="CSV dataset to analyze.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT,
        help="Directory where demo artifacts are written.",
    )
    parser.add_argument(
        "--task",
        default=DEFAULT_TASK,
        help="Natural-language workflow request for the planner.",
    )
    args = parser.parse_args(argv)

    demo = run_demo(dataset_path=args.dataset, artifact_root=args.artifact_root, task=args.task)
    print(f"Run ID: {demo.run_id}")
    print(f"Status: {demo.status.value}")
    print(f"Trace ID: {demo.trace_id}")
    print(f"Artifact root: {demo.artifact_root}")
    print(f"Summary: {demo.summary_path}")
    print(f"Metrics: {demo.metrics_path}")
    print(f"Events: {demo.event_count}")

    for artifact_type in (ArtifactType.DASHBOARD, ArtifactType.REPORT, ArtifactType.EVALUATION):
        matching = [
            artifact
            for artifact in demo.artifacts
            if artifact["type"] == artifact_type.value
        ]
        for artifact in matching:
            print(f"{artifact_type.value.title()}: {artifact['uri']}")

    if demo.evaluations:
        evaluation = demo.evaluations[-1]
        print(
            "Evaluation: "
            f"passed={evaluation['passed']} score={evaluation['score']} "
            f"checks={evaluation['check_count']}"
        )

    return 0 if demo.status == RunStatus.COMPLETED else 1


def _artifact_summary(artifact: ArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "type": artifact.type.value,
        "uri": artifact.uri,
        "producer_node_id": artifact.producer_node_id,
        "source_artifact_ids": list(artifact.source_artifact_ids),
        "metadata": dict(artifact.metadata),
    }


def _evaluation_summary(evaluation: EvaluationResultRecord) -> dict[str, Any]:
    return {
        "id": evaluation.id,
        "target_artifact_id": evaluation.target_artifact_id,
        "score": evaluation.score,
        "passed": evaluation.passed,
        "check_count": len(evaluation.checks),
        "checks": list(evaluation.checks),
        "created_at": evaluation.created_at.isoformat() if evaluation.created_at else None,
    }


if __name__ == "__main__":
    raise SystemExit(main())

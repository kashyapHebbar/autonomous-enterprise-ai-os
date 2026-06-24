from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def assert_exists(path: Path) -> None:
    if not path.exists():
        raise AssertionError(f"Missing expected path: {path.relative_to(ROOT)}")


def main() -> int:
    expected_paths = [
        ROOT / "pyproject.toml",
        ROOT / "docker-compose.yml",
        ROOT / "Dockerfile",
        ROOT / "README.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "development.md",
        ROOT / "src" / "aeai_os" / "api",
        ROOT / "src" / "aeai_os" / "agents",
        ROOT / "src" / "aeai_os" / "analytics",
        ROOT / "src" / "aeai_os" / "artifacts",
        ROOT / "src" / "aeai_os" / "data",
        ROOT / "src" / "aeai_os" / "orchestration",
        ROOT / "src" / "aeai_os" / "reports",
        ROOT / "src" / "aeai_os" / "schemas",
        ROOT / "src" / "aeai_os" / "security",
        ROOT / "src" / "aeai_os" / "observability",
        ROOT / "src" / "aeai_os" / "storage",
        ROOT / "src" / "aeai_os" / "evaluation",
        ROOT / "src" / "aeai_os" / "runs",
        ROOT / "src" / "aeai_os" / "visualization",
        ROOT / "tests",
    ]

    for path in expected_paths:
        assert_exists(path)

    from aeai_os.api.health import build_health_payload

    payload = build_health_payload()
    if payload["status"] != "ok":
        raise AssertionError(f"Unexpected health status: {payload['status']}")

    components = {component["name"] for component in payload["components"]}
    for required in {"api", "orchestrator", "agent_registry", "artifact_store"}:
        if required not in components:
            raise AssertionError(f"Missing health component: {required}")

    from aeai_os.agents.analytics_code import AnalyticsCodeAgent
    from aeai_os.agents.data_retrieval import DataRetrievalAgent
    from aeai_os.agents.evaluation import EvaluationAgent
    from aeai_os.agents.planner import PlannerAgent
    from aeai_os.agents.registry import build_default_registry
    from aeai_os.agents.report import ReportAgent
    from aeai_os.agents.visualization import VisualizationAgent
    from aeai_os.observability.metrics import render_prometheus_metrics
    from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode
    from aeai_os.orchestration.service import OrchestratorService
    from aeai_os.runs.repository import InMemoryRunRepository
    from aeai_os.schemas.enums import ArtifactType, RunStatus

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        csv_path = tmp_path / "procurement.csv"
        csv_path.write_text(
            "\n".join(
                [
                    "supplier,category,invoice_date,spend_amount",
                    "Acme,Software,2026-01-10,1200.50",
                    "Zenith,Hardware,2026-01-11,800.00",
                ]
            ),
            encoding="utf-8",
        )

        repository = InMemoryRunRepository()
        run = repository.create_run("Analyze this procurement dataset and create a dashboard.")
        if run.status != RunStatus.PENDING:
            raise AssertionError(f"Unexpected initial run status: {run.status}")
        if not run.trace_id:
            raise AssertionError("Run did not receive an observability trace ID.")

        artifact = repository.add_artifact(
            run_id=run.id,
            artifact_type=ArtifactType.DATASET,
            uri=str(csv_path),
            metadata={"source": "smoke", "format": "csv"},
        )
        updated_run = repository.get_run(run.id)
        if updated_run.dataset_artifact_id != artifact.id:
            raise AssertionError("Dataset artifact was not attached to the run.")

        planner = PlannerAgent()
        plan = planner.create_plan(
            run_id=run.id,
            user_task="Analyze this procurement dataset and create a dashboard.",
            dataset_artifact_id=artifact.id,
        )
        if not plan.nodes[0].required_tools:
            raise AssertionError("Planner did not include required tools.")
        plan.to_execution_graph().validate(set(build_default_registry().list_agent_types()))

        service = OrchestratorService(
            repository=repository,
            registry=build_default_registry(),
            agents={
                "data_retrieval": DataRetrievalAgent(
                    repository=repository,
                    artifact_root=tmp_path / "artifacts",
                ),
                "analytics_code": AnalyticsCodeAgent(
                    repository=repository,
                    artifact_root=tmp_path / "artifacts",
                ),
                "visualization": VisualizationAgent(
                    repository=repository,
                    artifact_root=tmp_path / "artifacts",
                ),
                "report": ReportAgent(
                    repository=repository,
                    artifact_root=tmp_path / "artifacts",
                ),
                "evaluation": EvaluationAgent(
                    repository=repository,
                    artifact_root=tmp_path / "artifacts",
                ),
            },
        )
        graph = ExecutionGraph(
            run_id=run.id,
            nodes=[
                ExecutionNode(
                    id="data_profile",
                    agent="data_retrieval",
                    task="Profile the procurement dataset.",
                    required_tools=["dataset_reader", "schema_profiler", "quality_checker"],
                    expected_artifacts=["schema_profile", "quality_report"],
                ),
                ExecutionNode(
                    id="analytics",
                    agent="analytics_code",
                    task="Compute procurement KPIs.",
                    depends_on=["data_profile"],
                    required_tools=["dataframe_query", "python_analysis", "code_artifact_writer"],
                    expected_artifacts=["kpi_table", "code"],
                    risk="medium",
                ),
                ExecutionNode(
                    id="visualization",
                    agent="visualization",
                    task="Create procurement dashboard charts.",
                    depends_on=["analytics"],
                    required_tools=["chart_renderer", "dashboard_renderer"],
                    expected_artifacts=["chart", "dashboard"],
                ),
                ExecutionNode(
                    id="report",
                    agent="report",
                    task="Generate final procurement report.",
                    depends_on=["visualization"],
                    required_tools=["artifact_reader", "markdown_report_writer"],
                    expected_artifacts=["report"],
                ),
                ExecutionNode(
                    id="evaluation",
                    agent="evaluation",
                    task="Evaluate procurement outputs.",
                    depends_on=["report"],
                    required_tools=[
                        "artifact_reader",
                        "deterministic_evaluator",
                        "evaluation_writer",
                    ],
                    expected_artifacts=["evaluation"],
                ),
            ],
        )
        result = service.execute_run(run.id, graph)
        if result.status != RunStatus.COMPLETED:
            raise AssertionError(f"Unexpected orchestrator result: {result.status}")

        artifact_types = {artifact.type for artifact in repository.list_artifacts(run.id)}
        expected_artifact_types = {
            ArtifactType.SCHEMA_PROFILE,
            ArtifactType.QUALITY_REPORT,
            ArtifactType.KPI_TABLE,
            ArtifactType.CODE,
            ArtifactType.CHART,
            ArtifactType.DASHBOARD,
            ArtifactType.REPORT,
            ArtifactType.EVALUATION,
        }
        if expected_artifact_types - artifact_types:
            raise AssertionError(
                "Data, analytics, visualization, report, and evaluation agents did not register "
                "expected artifacts."
            )
        evaluations = repository.list_evaluations(run.id)
        if not evaluations or not evaluations[-1].passed:
            raise AssertionError("Evaluation agent did not produce a passing evaluation result.")
        tool_events = [
            event for event in repository.list_events(run.id) if event.event_type == "tool_call"
        ]
        if not tool_events:
            raise AssertionError("Security policy did not record tool audit events.")
        if not all(event.payload.get("trace_id") for event in repository.list_events(run.id)):
            raise AssertionError("Observed agent events are missing trace IDs.")
        metrics = render_prometheus_metrics(repository)
        for expected_metric in (
            "aeai_runs_total 1",
            "aeai_artifacts_total",
            "aeai_evaluations_total 1",
            "aeai_agent_node_executions_total",
        ):
            if expected_metric not in metrics:
                raise AssertionError(f"Missing expected metric: {expected_metric}")

    print(
        "Smoke check passed: run lifecycle, data ingestion, analytics, visualization, and "
        "reporting/evaluation are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

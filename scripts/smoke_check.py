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
        ROOT / "src" / "aeai_os" / "data",
        ROOT / "src" / "aeai_os" / "orchestration",
        ROOT / "src" / "aeai_os" / "schemas",
        ROOT / "src" / "aeai_os" / "storage",
        ROOT / "src" / "aeai_os" / "evaluation",
        ROOT / "src" / "aeai_os" / "runs",
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

    from aeai_os.agents.data_retrieval import DataRetrievalAgent
    from aeai_os.agents.planner import PlannerAgent
    from aeai_os.agents.registry import build_default_registry
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
                )
            },
        )
        graph = ExecutionGraph(
            run_id=run.id,
            nodes=[
                ExecutionNode(
                    id="data_profile",
                    agent="data_retrieval",
                    task="Profile the procurement dataset.",
                    expected_artifacts=["schema_profile", "quality_report"],
                )
            ],
        )
        result = service.execute_run(run.id, graph)
        if result.status != RunStatus.COMPLETED:
            raise AssertionError(f"Unexpected orchestrator result: {result.status}")

        artifact_types = {artifact.type for artifact in repository.list_artifacts(run.id)}
        if {ArtifactType.SCHEMA_PROFILE, ArtifactType.QUALITY_REPORT} - artifact_types:
            raise AssertionError("Data retrieval agent did not register profile artifacts.")

    print(
        "Smoke check passed: scaffold, run lifecycle, orchestrator, and data ingestion are valid."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

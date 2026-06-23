from __future__ import annotations

from pathlib import Path

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.base import AgentInput
from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.agents.evaluation import EvaluationAgent
from aeai_os.agents.report import ReportAgent
from aeai_os.agents.visualization import VisualizationAgent
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType


def write_evaluation_fixture(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-05,100,IT",
                "Acme,Software,2026-01-06,100,IT",
                "Zenith,Hardware,2026-02-01,200,Operations",
                "Acme,Cloud,2026-02-10,1000,IT",
                "Acme,,2026-02-11,,Finance",
                "Tiny,Office,2026-03-01,10,Finance",
            ]
        ),
        encoding="utf-8",
    )


def build_evaluation_fixture(tmp_path: Path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    run = repository.create_run("Analyze procurement data and create a dashboard report.")
    csv_path = tmp_path / "procurement.csv"
    write_evaluation_fixture(csv_path)
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(csv_path),
        metadata={"source": "test", "format": "csv"},
    )
    data_output = DataRetrievalAgent(repository, artifact_root).execute(
        AgentInput(
            run_id=run.id,
            node_id="data_profile",
            task="Profile procurement dataset.",
            context={"dataset_artifact_id": dataset.id},
        )
    )
    analytics_output = AnalyticsCodeAgent(repository, artifact_root).execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id},
            artifacts=data_output.artifacts,
        )
    )
    visualization_output = VisualizationAgent(repository, artifact_root).execute(
        AgentInput(
            run_id=run.id,
            node_id="visualization",
            task="Create procurement dashboard.",
            artifacts=[*data_output.artifacts, *analytics_output.artifacts],
        )
    )
    report_output = ReportAgent(repository, artifact_root).execute(
        AgentInput(
            run_id=run.id,
            node_id="report",
            task="Generate final procurement report.",
            artifacts=[
                *data_output.artifacts,
                *analytics_output.artifacts,
                *visualization_output.artifacts,
            ],
        )
    )
    agent = EvaluationAgent(repository=repository, artifact_root=artifact_root)
    upstream_artifacts = [
        *data_output.artifacts,
        *analytics_output.artifacts,
        *visualization_output.artifacts,
        *report_output.artifacts,
    ]
    return repository, run, agent, upstream_artifacts


def test_evaluation_agent_passes_structured_quality_gates(tmp_path):
    repository, run, agent, upstream_artifacts = build_evaluation_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="evaluation",
            task="Evaluate procurement outputs.",
            artifacts=upstream_artifacts,
        )
    )

    evaluation_artifact = repository.get_artifact(run.id, output.artifacts[0])
    evaluation_record = repository.list_evaluations(run.id)[0]
    check_results = {check["name"]: check for check in evaluation_record.checks}

    assert output.status == "succeeded"
    assert evaluation_artifact.type == ArtifactType.EVALUATION
    assert evaluation_artifact.metadata["passed"] is True
    assert evaluation_record.passed is True
    assert evaluation_record.score == 1.0
    assert {
        "artifact_completeness",
        "task_completion",
        "data_consistency",
        "assumption_disclosure",
    } == set(check_results)
    assert check_results["data_consistency"]["passed"] is True
    assert check_results["data_consistency"]["details"]["report_matches"] is True
    assert check_results["data_consistency"]["details"]["chart_matches"] is True


def test_evaluation_agent_fails_intentionally_inconsistent_report(tmp_path):
    repository, run, agent, upstream_artifacts = build_evaluation_fixture(tmp_path)
    report_artifact = next(
        artifact
        for artifact in repository.list_artifacts(run.id)
        if artifact.type == ArtifactType.REPORT
    )
    report_path = Path(report_artifact.uri)
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace("$1,410.00", "$999,999.00"),
        encoding="utf-8",
    )

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="evaluation",
            task="Evaluate procurement outputs.",
            artifacts=upstream_artifacts,
        )
    )

    evaluation_artifact = repository.get_artifact(run.id, output.artifacts[0])
    evaluation_record = repository.list_evaluations(run.id)[0]
    check_results = {check["name"]: check for check in evaluation_record.checks}

    assert output.status == "failed"
    assert "data_consistency" in output.errors[0]
    assert evaluation_artifact.metadata["passed"] is False
    assert evaluation_record.passed is False
    assert evaluation_record.score < 1.0
    assert check_results["data_consistency"]["passed"] is False
    assert check_results["data_consistency"]["details"]["report_matches"] is False
    assert check_results["data_consistency"]["details"]["chart_matches"] is True

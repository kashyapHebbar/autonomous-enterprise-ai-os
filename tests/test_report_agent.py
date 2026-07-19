from __future__ import annotations

from pathlib import Path

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.base import AgentInput
from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.agents.report import ReportAgent
from aeai_os.agents.visualization import VisualizationAgent
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.reports.procurement import render_procurement_markdown_report
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType


def write_report_fixture(path: Path) -> None:
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


def build_report_fixture(tmp_path: Path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    run = repository.create_run("Analyze procurement data and create a dashboard report.")
    csv_path = tmp_path / "procurement.csv"
    write_report_fixture(csv_path)
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
    agent = ReportAgent(repository=repository, artifact_root=artifact_root)
    upstream_artifacts = [
        *data_output.artifacts,
        *analytics_output.artifacts,
        *visualization_output.artifacts,
    ]
    return repository, run, dataset, agent, upstream_artifacts


def test_report_agent_generates_markdown_report_with_lineage(tmp_path):
    repository, run, dataset, agent, upstream_artifacts = build_report_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="report",
            task="Generate final procurement report.",
            artifacts=upstream_artifacts,
        )
    )

    report_artifact = repository.get_artifact(run.id, output.artifacts[0])
    report_markdown = Path(report_artifact.uri).read_text(encoding="utf-8")
    source_types = {
        repository.get_artifact(run.id, artifact_id).type
        for artifact_id in report_artifact.source_artifact_ids
    }

    assert output.status == "succeeded"
    assert report_artifact.type == ArtifactType.REPORT
    assert report_artifact.producer_node_id == "report"
    assert report_artifact.metadata["format"] == "markdown"
    assert report_artifact.metadata["chart_count"] >= 4
    assert "## Anomaly Intelligence" in report_markdown
    assert dataset.id in report_artifact.source_artifact_ids
    assert {
        ArtifactType.DATASET,
        ArtifactType.SCHEMA_PROFILE,
        ArtifactType.QUALITY_REPORT,
        ArtifactType.KPI_TABLE,
        ArtifactType.CHART,
        ArtifactType.DASHBOARD,
    }.issubset(source_types)
    assert "# Procurement Analysis Report" in report_markdown
    assert "## Charts And Dashboard" in report_markdown
    assert "Supplier Spend Concentration" in report_markdown
    assert "## Assumptions" in report_markdown
    assert "## Limitations" in report_markdown
    assert "## Artifact Lineage" in report_markdown

    lineage = ArtifactLineageService(repository).build_lineage(run.id, report_artifact.id)
    upstream_ids = {artifact.id for artifact in lineage.upstream_artifacts}
    assert dataset.id in upstream_ids
    assert any(edge.target_artifact_id == report_artifact.id for edge in lineage.edges)


def test_report_agent_fails_without_kpi_artifact(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Generate a report.")
    agent = ReportAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="report",
            task="Generate final procurement report.",
        )
    )

    assert output.status == "failed"
    assert "No kpi_table artifact" in output.errors[0]
    assert repository.list_artifacts(run.id) == []


def test_procurement_report_renders_dataset_currency():
    analysis = {
        "dataset": {"currency": "GBP", "currency_symbol": "£"},
        "kpis": {
            "total_spend": 3427.96,
            "supplier_count": 2,
            "category_count": 2,
            "average_transaction_value": 1713.98,
            "outlier_count": 0,
            "estimated_savings": 100,
        },
        "insights": ["Total analyzed procurement spend is £3,427.96."],
        "savings_opportunities": [],
        "missing_data_risks": [],
    }

    report = render_procurement_markdown_report(analysis, [])

    assert "£3,427.96" in report
    assert "$" not in report

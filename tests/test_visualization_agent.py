from __future__ import annotations

from pathlib import Path

import pytest

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.base import AgentInput
from aeai_os.agents.visualization import VisualizationAgent
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType
from aeai_os.visualization import VisualizationError, build_procurement_chart_specs


def write_visualization_fixture(path: Path) -> None:
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


def build_visualization_fixture(tmp_path: Path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data and create a dashboard.")
    csv_path = tmp_path / "procurement.csv"
    write_visualization_fixture(csv_path)
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(csv_path),
        metadata={"source": "test", "format": "csv"},
    )
    analytics = AnalyticsCodeAgent(repository=repository, artifact_root=tmp_path / "artifacts")
    analytics_output = analytics.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id},
        )
    )
    kpi_artifact = repository.get_artifact(run.id, analytics_output.artifacts[0])
    agent = VisualizationAgent(repository=repository, artifact_root=tmp_path / "artifacts")
    return repository, run, kpi_artifact, agent


def test_visualization_agent_registers_chart_and_dashboard_artifacts(tmp_path):
    repository, run, kpi_artifact, agent = build_visualization_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="visualization",
            task="Create procurement dashboard.",
            artifacts=[kpi_artifact.id],
        )
    )

    output_artifacts = [
        repository.get_artifact(run.id, artifact_id) for artifact_id in output.artifacts
    ]
    chart_artifacts = [
        artifact for artifact in output_artifacts if artifact.type == ArtifactType.CHART
    ]
    dashboard_artifact = next(
        artifact for artifact in output_artifacts if artifact.type == ArtifactType.DASHBOARD
    )
    dashboard_html = Path(dashboard_artifact.uri).read_text(encoding="utf-8")

    assert output.status == "succeeded"
    assert len(chart_artifacts) >= 4
    assert output.metrics["chart_count"] == len(chart_artifacts)
    assert dashboard_artifact.metadata["format"] == "html"
    assert dashboard_artifact.source_artifact_ids[0] == kpi_artifact.id
    assert {artifact.id for artifact in chart_artifacts}.issubset(
        set(dashboard_artifact.source_artifact_ids)
    )
    assert "Procurement Dashboard" in dashboard_html
    assert "Executive procurement intelligence" in dashboard_html
    assert "Executive Insights" in dashboard_html
    assert kpi_artifact.id in dashboard_html

    chart_titles = {artifact.metadata["title"] for artifact in chart_artifacts}
    assert {
        "Key Procurement KPIs",
        "Supplier Spend Concentration",
        "Category Spend Breakdown",
        "Monthly Spend Trend",
        "Anomaly Review",
    } == chart_titles

    for chart_artifact in chart_artifacts:
        chart_html = Path(chart_artifact.uri).read_text(encoding="utf-8")
        assert chart_artifact.source_artifact_ids == [kpi_artifact.id]
        assert chart_artifact.metadata["format"] == "html"
        assert chart_artifact.metadata["title"] in dashboard_html
        assert f'data-source-artifact-id="{kpi_artifact.id}"' in chart_html
        assert 'data-role="chart-data"' in chart_html


def test_visualization_agent_resolves_latest_kpi_artifact_from_run(tmp_path):
    repository, run, kpi_artifact, agent = build_visualization_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="visualization",
            task="Create procurement dashboard.",
        )
    )

    dashboard_artifact = repository.get_artifact(run.id, output.artifacts[-1])
    assert output.status == "succeeded"
    assert output.metrics["source_artifact_id"] == kpi_artifact.id
    assert dashboard_artifact.type == ArtifactType.DASHBOARD


def test_visualization_agent_fails_without_kpi_artifact(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Create a dashboard.")
    agent = VisualizationAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="visualization",
            task="Create procurement dashboard.",
        )
    )

    assert output.status == "failed"
    assert "No KPI table artifact" in output.errors[0]
    assert repository.list_artifacts(run.id) == []


def test_chart_specs_validate_required_analysis_sections():
    with pytest.raises(VisualizationError) as exc_info:
        build_procurement_chart_specs({"kpis": {}})

    assert "missing required sections" in str(exc_info.value)


def test_chart_specs_render_dataset_currency():
    analysis = {
        "dataset": {"currency": "GBP", "currency_symbol": "£"},
        "kpis": {
            "total_spend": 3427.96,
            "supplier_count": 2,
            "category_count": 2,
            "outlier_count": 0,
            "estimated_savings": 100,
        },
        "spend_by_supplier": [{"supplier": "Acme", "spend": 3427.96, "share": 1.0}],
        "spend_by_category": [{"category": "Software", "spend": 3427.96, "share": 1.0}],
        "spend_trend": [{"month": "2025-03", "spend": 3427.96}],
        "outliers": [],
    }

    specs = build_procurement_chart_specs(analysis)

    assert all("$" not in spec.body_html for spec in specs)
    assert "£3,427.96" in specs[0].body_html
    assert "£3.4K" in specs[3].body_html

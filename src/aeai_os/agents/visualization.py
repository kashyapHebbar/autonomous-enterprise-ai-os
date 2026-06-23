from __future__ import annotations

import json
from pathlib import Path

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.visualization import (
    VisualizationError,
    build_procurement_chart_specs,
    render_chart_document,
    render_dashboard_document,
)


class VisualizationAgent:
    agent_type = "visualization"

    def __init__(self, repository: InMemoryRunRepository, artifact_root: str | Path) -> None:
        self._repository = repository
        self._artifact_root = Path(artifact_root)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            kpi_artifact = self._resolve_kpi_artifact(agent_input)
            analysis = json.loads(Path(kpi_artifact.uri).read_text(encoding="utf-8"))
            charts = build_procurement_chart_specs(analysis)
            if len(charts) < 4:
                raise VisualizationError("Dashboard requires at least four chart specs.")

            output_dir = self._artifact_root / agent_input.run_id / agent_input.node_id
            output_dir.mkdir(parents=True, exist_ok=True)

            chart_artifacts: list[ArtifactRecord] = []
            for chart in charts:
                chart_path = output_dir / f"{chart.slug}.html"
                chart_path.write_text(
                    render_chart_document(chart, source_artifact_id=kpi_artifact.id),
                    encoding="utf-8",
                )
                chart_artifacts.append(
                    self._repository.add_artifact(
                        run_id=agent_input.run_id,
                        artifact_type=ArtifactType.CHART,
                        uri=str(chart_path),
                        metadata={
                            "source": "visualization_agent",
                            "format": "html",
                            "chart_slug": chart.slug,
                            "chart_type": chart.chart_type,
                            "title": chart.title,
                            "data_points": len(chart.data),
                        },
                        source_artifact_ids=[kpi_artifact.id],
                        producer_node_id=agent_input.node_id,
                    )
                )

            dashboard_path = output_dir / "procurement_dashboard.html"
            dashboard_path.write_text(
                render_dashboard_document(
                    analysis=analysis,
                    charts=charts,
                    source_artifact_id=kpi_artifact.id,
                    chart_artifact_ids=[artifact.id for artifact in chart_artifacts],
                ),
                encoding="utf-8",
            )
            dashboard_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.DASHBOARD,
                uri=str(dashboard_path),
                metadata={
                    "source": "visualization_agent",
                    "format": "html",
                    "chart_count": len(chart_artifacts),
                    "title": "Procurement Dashboard",
                },
                source_artifact_ids=[
                    kpi_artifact.id,
                    *[artifact.id for artifact in chart_artifacts],
                ],
                producer_node_id=agent_input.node_id,
            )
        except (
            VisualizationError,
            ArtifactNotFoundError,
            KeyError,
            OSError,
            json.JSONDecodeError,
        ) as exc:
            return AgentOutput(
                status="failed",
                summary="Visualization agent failed to generate dashboard artifacts.",
                errors=[str(exc)],
                events=[
                    {
                        "event_type": AgentEventType.ERROR,
                        "message": str(exc),
                    }
                ],
            )

        artifact_ids = [artifact.id for artifact in chart_artifacts] + [dashboard_artifact.id]
        return AgentOutput(
            status="succeeded",
            summary=(
                f"Generated procurement dashboard with {len(chart_artifacts)} chart artifacts."
            ),
            artifacts=artifact_ids,
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Procurement chart and dashboard artifacts registered.",
                    "kpi_artifact_id": kpi_artifact.id,
                    "dashboard_artifact_id": dashboard_artifact.id,
                    "chart_artifact_ids": [artifact.id for artifact in chart_artifacts],
                }
            ],
            metrics={
                "chart_count": len(chart_artifacts),
                "dashboard_artifact_id": dashboard_artifact.id,
                "source_artifact_id": kpi_artifact.id,
                "chart_titles": [chart.title for chart in charts],
            },
        )

    def _resolve_kpi_artifact(self, agent_input: AgentInput) -> ArtifactRecord:
        explicit_artifact_id = agent_input.context.get("kpi_artifact_id")
        if explicit_artifact_id:
            artifact = self._repository.get_artifact(agent_input.run_id, explicit_artifact_id)
            if artifact.type != ArtifactType.KPI_TABLE:
                raise VisualizationError(f"Artifact is not a KPI table: {explicit_artifact_id}")
            return artifact

        for artifact_id in reversed(agent_input.artifacts):
            try:
                artifact = self._repository.get_artifact(agent_input.run_id, artifact_id)
            except ArtifactNotFoundError:
                continue
            if artifact.type == ArtifactType.KPI_TABLE:
                return artifact

        for artifact in reversed(self._repository.list_artifacts(agent_input.run_id)):
            if artifact.type == ArtifactType.KPI_TABLE:
                return artifact

        raise VisualizationError("No KPI table artifact is available for visualization.")

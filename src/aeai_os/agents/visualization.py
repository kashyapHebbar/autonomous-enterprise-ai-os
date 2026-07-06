from __future__ import annotations

from pathlib import Path

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.storage import ArtifactStorageError, ArtifactStore, LocalArtifactStore
from aeai_os.visualization import (
    VisualizationError,
    build_procurement_chart_specs,
    render_chart_document,
    render_dashboard_document,
)


class VisualizationAgent:
    agent_type = "visualization"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store or LocalArtifactStore(artifact_root)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            kpi_artifact = self._resolve_kpi_artifact(agent_input)
            analysis = self._artifact_store.read_json(kpi_artifact.uri)
            charts = build_procurement_chart_specs(analysis)
            if len(charts) < 4:
                raise VisualizationError("Dashboard requires at least four chart specs.")

            chart_artifacts: list[ArtifactRecord] = []
            for chart in charts:
                chart_artifact_id = self._repository.next_artifact_id()
                chart_payload = self._artifact_store.write_text(
                    run_id=agent_input.run_id,
                    node_id=agent_input.node_id,
                    filename=f"{chart.slug}.html",
                    payload=render_chart_document(chart, source_artifact_id=kpi_artifact.id),
                    content_type="text/html; charset=utf-8",
                )
                chart_artifacts.append(
                    self._repository.add_artifact(
                        run_id=agent_input.run_id,
                        artifact_type=ArtifactType.CHART,
                        artifact_id=chart_artifact_id,
                        uri=chart_payload.uri,
                        metadata={
                            "source": "visualization_agent",
                            "format": "html",
                            "chart_slug": chart.slug,
                            "chart_type": chart.chart_type,
                            "title": chart.title,
                            "data_points": len(chart.data),
                            **chart_payload.metadata,
                        },
                        source_artifact_ids=[kpi_artifact.id],
                        producer_node_id=agent_input.node_id,
                    )
                )

            dashboard_artifact_id = self._repository.next_artifact_id()
            dashboard_payload = self._artifact_store.write_text(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="procurement_dashboard.html",
                payload=render_dashboard_document(
                    analysis=analysis,
                    charts=charts,
                    source_artifact_id=kpi_artifact.id,
                    chart_artifact_ids=[artifact.id for artifact in chart_artifacts],
                ),
                content_type="text/html; charset=utf-8",
            )
            dashboard_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.DASHBOARD,
                artifact_id=dashboard_artifact_id,
                uri=dashboard_payload.uri,
                metadata={
                    "source": "visualization_agent",
                    "format": "html",
                    "chart_count": len(chart_artifacts),
                    "title": "Procurement Dashboard",
                    **dashboard_payload.metadata,
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
            ArtifactStorageError,
            KeyError,
            OSError,
            ValueError,
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

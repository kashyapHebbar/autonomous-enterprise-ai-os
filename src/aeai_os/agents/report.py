from __future__ import annotations

from pathlib import Path
from typing import Any

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.reports import render_generic_markdown_report, render_procurement_markdown_report
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.storage import ArtifactStorageError, ArtifactStore, LocalArtifactStore


class ReportAgent:
    agent_type = "report"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        lineage_service: ArtifactLineageService | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store or LocalArtifactStore(artifact_root)
        self._lineage_service = lineage_service or ArtifactLineageService(repository)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            kpi_artifact = self._resolve_latest_artifact(agent_input, ArtifactType.KPI_TABLE)
            analysis = _read_json_artifact(kpi_artifact, self._artifact_store)
            schema_artifact = self._resolve_latest_artifact(
                agent_input, ArtifactType.SCHEMA_PROFILE, required=False
            )
            quality_artifact = self._resolve_latest_artifact(
                agent_input, ArtifactType.QUALITY_REPORT, required=False
            )
            chart_artifacts = self._resolve_artifacts(agent_input, ArtifactType.CHART)
            dashboard_artifact = self._resolve_latest_artifact(
                agent_input, ArtifactType.DASHBOARD, required=False
            )

            report_sources = [
                artifact
                for artifact in [
                    kpi_artifact,
                    schema_artifact,
                    quality_artifact,
                    *chart_artifacts,
                    dashboard_artifact,
                ]
                if artifact is not None
            ]
            source_artifact_ids = self._lineage_service.expand_source_artifact_ids(
                agent_input.run_id,
                [artifact.id for artifact in report_sources],
            )
            lineage_artifacts = [
                self._repository.get_artifact(agent_input.run_id, artifact_id)
                for artifact_id in source_artifact_ids
            ]
            analysis_type = str(analysis.get("analysis_type") or "procurement")
            report_renderer = (
                render_generic_markdown_report
                if analysis_type == "generic"
                else render_procurement_markdown_report
            )
            report_markdown = report_renderer(
                analysis=analysis,
                artifacts=lineage_artifacts,
                schema_profile=(
                    _read_json_artifact(schema_artifact, self._artifact_store)
                    if schema_artifact is not None
                    else None
                ),
                quality_report=(
                    _read_json_artifact(quality_artifact, self._artifact_store)
                    if quality_artifact is not None
                    else None
                ),
            )

            report_artifact_id = self._repository.next_artifact_id()
            report_payload = self._artifact_store.write_text(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename=f"{analysis_type}_report.md",
                payload=report_markdown,
                content_type="text/markdown; charset=utf-8",
            )
            report_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.REPORT,
                artifact_id=report_artifact_id,
                uri=report_payload.uri,
                metadata={
                    "source": "report_agent",
                    "format": "markdown",
                    "title": (
                        "Exploratory Dataset Analysis Report"
                        if analysis_type == "generic"
                        else "Procurement Analysis Report"
                    ),
                    "analysis_type": analysis_type,
                    "chart_count": len(chart_artifacts),
                    "source_artifact_count": len(source_artifact_ids),
                    "included_sections": [
                        "executive_summary",
                        "key_findings",
                        "kpis",
                        "dataset_quality",
                        "charts",
                        "recommendations",
                        "assumptions",
                        "limitations",
                    ],
                    **report_payload.metadata,
                },
                source_artifact_ids=source_artifact_ids,
                producer_node_id=agent_input.node_id,
            )
        except (ArtifactNotFoundError, ArtifactStorageError, KeyError, OSError, ValueError) as exc:
            return AgentOutput(
                status="failed",
                summary="Report agent failed to generate the analysis report.",
                errors=[str(exc)],
                events=[
                    {
                        "event_type": AgentEventType.ERROR,
                        "message": str(exc),
                    }
                ],
            )

        return AgentOutput(
            status="succeeded",
            summary=f"Generated {analysis_type} Markdown report with artifact lineage.",
            artifacts=[report_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Analysis report artifact registered.",
                    "report_artifact_id": report_artifact.id,
                    "source_artifact_ids": source_artifact_ids,
                }
            ],
            metrics={
                "report_artifact_id": report_artifact.id,
                "chart_count": len(chart_artifacts),
                "source_artifact_count": len(source_artifact_ids),
            },
        )

    def _resolve_latest_artifact(
        self,
        agent_input: AgentInput,
        artifact_type: ArtifactType,
        required: bool = True,
    ) -> ArtifactRecord | None:
        for artifact in reversed(self._candidate_artifacts(agent_input)):
            if artifact.type == artifact_type:
                return artifact
        if required:
            raise ValueError(f"No {artifact_type.value} artifact is available for reporting.")
        return None

    def _resolve_artifacts(
        self,
        agent_input: AgentInput,
        artifact_type: ArtifactType,
    ) -> list[ArtifactRecord]:
        return [
            artifact
            for artifact in self._candidate_artifacts(agent_input)
            if artifact.type == artifact_type
        ]

    def _candidate_artifacts(self, agent_input: AgentInput) -> list[ArtifactRecord]:
        artifacts_by_id: dict[str, ArtifactRecord] = {}
        for artifact_id in agent_input.artifacts:
            try:
                artifact = self._repository.get_artifact(agent_input.run_id, artifact_id)
            except ArtifactNotFoundError:
                continue
            artifacts_by_id[artifact.id] = artifact
        for artifact in self._repository.list_artifacts(agent_input.run_id):
            artifacts_by_id[artifact.id] = artifact
        return list(artifacts_by_id.values())


def _read_json_artifact(artifact: ArtifactRecord, artifact_store: ArtifactStore) -> dict[str, Any]:
    try:
        return artifact_store.read_json(artifact.uri)
    except ArtifactStorageError as exc:
        raise ValueError(f"Artifact JSON payload must be readable: {artifact.id}") from exc

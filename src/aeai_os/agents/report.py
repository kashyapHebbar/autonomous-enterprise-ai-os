from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.reports import render_procurement_markdown_report
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType


class ReportAgent:
    agent_type = "report"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        lineage_service: ArtifactLineageService | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_root = Path(artifact_root)
        self._lineage_service = lineage_service or ArtifactLineageService(repository)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            kpi_artifact = self._resolve_latest_artifact(agent_input, ArtifactType.KPI_TABLE)
            analysis = _read_json_artifact(kpi_artifact)
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
            report_markdown = render_procurement_markdown_report(
                analysis=analysis,
                artifacts=lineage_artifacts,
                schema_profile=(
                    _read_json_artifact(schema_artifact) if schema_artifact is not None else None
                ),
                quality_report=(
                    _read_json_artifact(quality_artifact) if quality_artifact is not None else None
                ),
            )

            output_dir = self._artifact_root / agent_input.run_id / agent_input.node_id
            output_dir.mkdir(parents=True, exist_ok=True)
            report_path = output_dir / "procurement_report.md"
            report_path.write_text(report_markdown, encoding="utf-8")
            report_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.REPORT,
                uri=str(report_path),
                metadata={
                    "source": "report_agent",
                    "format": "markdown",
                    "title": "Procurement Analysis Report",
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
                },
                source_artifact_ids=source_artifact_ids,
                producer_node_id=agent_input.node_id,
            )
        except (ArtifactNotFoundError, KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
            return AgentOutput(
                status="failed",
                summary="Report agent failed to generate the procurement report.",
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
            summary="Generated procurement Markdown report with artifact lineage.",
            artifacts=[report_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Procurement report artifact registered.",
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


def _read_json_artifact(artifact: ArtifactRecord) -> dict[str, Any]:
    payload = json.loads(Path(artifact.uri).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Artifact JSON payload must be an object: {artifact.id}")
    return payload

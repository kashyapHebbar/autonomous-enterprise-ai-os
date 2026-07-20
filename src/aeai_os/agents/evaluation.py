from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.evaluation import (
    evaluate_generic_outputs,
    evaluate_procurement_outputs,
    extract_embedded_chart_payload,
)
from aeai_os.runs.models import ArtifactRecord, EvaluationResultRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.storage import ArtifactStorageError, ArtifactStore, LocalArtifactStore


class EvaluationAgent:
    agent_type = "evaluation"

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
            artifacts = self._candidate_artifacts(agent_input)
            kpi_artifact = self._latest_artifact(artifacts, ArtifactType.KPI_TABLE)
            report_artifact = self._latest_artifact(artifacts, ArtifactType.REPORT)
            chart_artifacts = [
                artifact for artifact in artifacts if artifact.type == ArtifactType.CHART
            ]
            analysis = _read_json_artifact(kpi_artifact, self._artifact_store)
            report_markdown = self._artifact_store.read_text(report_artifact.uri)
            chart_payloads = _read_chart_payloads(chart_artifacts, self._artifact_store)

            evaluator = (
                evaluate_generic_outputs
                if analysis.get("analysis_type") == "generic"
                else evaluate_procurement_outputs
            )
            outcome = evaluator(
                analysis=analysis,
                report_markdown=report_markdown,
                artifacts=artifacts,
                chart_payloads=chart_payloads,
                target_artifact_id=report_artifact.id,
            )

            evaluation_artifact_id = self._repository.next_artifact_id()
            evaluation_payload = outcome.to_dict()
            stored_evaluation = self._artifact_store.write_json(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="evaluation_result.json",
                payload=evaluation_payload,
            )
            source_artifact_ids = _evaluation_source_ids(artifacts)
            evaluation_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.EVALUATION,
                artifact_id=evaluation_artifact_id,
                uri=stored_evaluation.uri,
                metadata={
                    "source": "evaluation_agent",
                    "format": "json",
                    "score": outcome.score,
                    "passed": outcome.passed,
                    "target_artifact_id": report_artifact.id,
                    "check_count": len(outcome.checks),
                    **stored_evaluation.metadata,
                },
                source_artifact_ids=source_artifact_ids,
                producer_node_id=agent_input.node_id,
            )
            self._repository.add_evaluation(
                EvaluationResultRecord(
                    id=f"evaluation_{uuid4().hex}",
                    run_id=agent_input.run_id,
                    target_artifact_id=report_artifact.id,
                    score=outcome.score,
                    passed=outcome.passed,
                    checks=outcome.checks,
                )
            )
        except (ArtifactNotFoundError, ArtifactStorageError, KeyError, OSError, ValueError) as exc:
            return AgentOutput(
                status="failed",
                summary="Evaluation agent failed to score the run outputs.",
                errors=[str(exc)],
                events=[
                    {
                        "event_type": AgentEventType.ERROR,
                        "message": str(exc),
                    }
                ],
            )

        failed_checks = [check["name"] for check in outcome.checks if not check["passed"]]
        if failed_checks:
            return AgentOutput(
                status="failed",
                summary=f"Evaluation failed with score {outcome.score}.",
                artifacts=[evaluation_artifact.id],
                errors=[f"Failed evaluation checks: {', '.join(failed_checks)}"],
                events=[
                    {
                        "event_type": AgentEventType.ERROR,
                        "message": "Evaluation quality gates failed.",
                        "evaluation_artifact_id": evaluation_artifact.id,
                        "failed_checks": failed_checks,
                    }
                ],
                metrics=_metrics(evaluation_artifact.id, outcome.to_dict()),
            )

        return AgentOutput(
            status="succeeded",
            summary=f"Evaluation passed with score {outcome.score}.",
            artifacts=[evaluation_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Evaluation quality gates passed.",
                    "evaluation_artifact_id": evaluation_artifact.id,
                }
            ],
            metrics=_metrics(evaluation_artifact.id, outcome.to_dict()),
        )

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

    @staticmethod
    def _latest_artifact(
        artifacts: list[ArtifactRecord],
        artifact_type: ArtifactType,
    ) -> ArtifactRecord:
        for artifact in reversed(artifacts):
            if artifact.type == artifact_type:
                return artifact
        raise ValueError(f"No {artifact_type.value} artifact is available for evaluation.")


def _read_json_artifact(artifact: ArtifactRecord, artifact_store: ArtifactStore) -> dict[str, Any]:
    try:
        return artifact_store.read_json(artifact.uri)
    except ArtifactStorageError as exc:
        raise ValueError(f"Artifact JSON payload must be readable: {artifact.id}") from exc


def _read_chart_payloads(
    chart_artifacts: list[ArtifactRecord],
    artifact_store: ArtifactStore,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for artifact in chart_artifacts:
        payload = extract_embedded_chart_payload(artifact_store.read_text(artifact.uri))
        if payload is not None:
            payloads.append(payload)
    return payloads


def _evaluation_source_ids(artifacts: list[ArtifactRecord]) -> list[str]:
    included_types = {
        ArtifactType.DATASET,
        ArtifactType.SCHEMA_PROFILE,
        ArtifactType.QUALITY_REPORT,
        ArtifactType.KPI_TABLE,
        ArtifactType.CHART,
        ArtifactType.DASHBOARD,
        ArtifactType.REPORT,
    }
    return [artifact.id for artifact in artifacts if artifact.type in included_types]


def _metrics(evaluation_artifact_id: str, outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation_artifact_id": evaluation_artifact_id,
        "score": outcome["score"],
        "passed": outcome["passed"],
        "checks": outcome["checks"],
    }

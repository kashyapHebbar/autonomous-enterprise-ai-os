from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.evaluation import evaluate_procurement_outputs, extract_embedded_chart_payload
from aeai_os.runs.models import ArtifactRecord, EvaluationResultRecord
from aeai_os.runs.repository import ArtifactNotFoundError, InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType


class EvaluationAgent:
    agent_type = "evaluation"

    def __init__(self, repository: InMemoryRunRepository, artifact_root: str | Path) -> None:
        self._repository = repository
        self._artifact_root = Path(artifact_root)

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            artifacts = self._candidate_artifacts(agent_input)
            kpi_artifact = self._latest_artifact(artifacts, ArtifactType.KPI_TABLE)
            report_artifact = self._latest_artifact(artifacts, ArtifactType.REPORT)
            chart_artifacts = [
                artifact for artifact in artifacts if artifact.type == ArtifactType.CHART
            ]
            analysis = _read_json_artifact(kpi_artifact)
            report_markdown = Path(report_artifact.uri).read_text(encoding="utf-8")
            chart_payloads = _read_chart_payloads(chart_artifacts)

            outcome = evaluate_procurement_outputs(
                analysis=analysis,
                report_markdown=report_markdown,
                artifacts=artifacts,
                chart_payloads=chart_payloads,
                target_artifact_id=report_artifact.id,
            )

            output_dir = self._artifact_root / agent_input.run_id / agent_input.node_id
            output_dir.mkdir(parents=True, exist_ok=True)
            evaluation_path = output_dir / "evaluation_result.json"
            evaluation_payload = outcome.to_dict()
            evaluation_path.write_text(
                json.dumps(evaluation_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            source_artifact_ids = _evaluation_source_ids(artifacts)
            evaluation_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.EVALUATION,
                uri=str(evaluation_path),
                metadata={
                    "source": "evaluation_agent",
                    "format": "json",
                    "score": outcome.score,
                    "passed": outcome.passed,
                    "target_artifact_id": report_artifact.id,
                    "check_count": len(outcome.checks),
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
        except (ArtifactNotFoundError, KeyError, OSError, json.JSONDecodeError, ValueError) as exc:
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


def _read_json_artifact(artifact: ArtifactRecord) -> dict[str, Any]:
    payload = json.loads(Path(artifact.uri).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Artifact JSON payload must be an object: {artifact.id}")
    return payload


def _read_chart_payloads(chart_artifacts: list[ArtifactRecord]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for artifact in chart_artifacts:
        payload = extract_embedded_chart_payload(Path(artifact.uri).read_text(encoding="utf-8"))
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

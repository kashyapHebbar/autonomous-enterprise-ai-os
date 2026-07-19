from __future__ import annotations

from pathlib import Path
from typing import Any

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.analytics import (
    AnalyticsError,
    CodeSafetyDecision,
    PythonCodeGuard,
    analyze_procurement_dataset,
)
from aeai_os.analytics.reproducible import generate_reproducible_analysis_code
from aeai_os.data import (
    CsvDatasetAdapter,
    DataIngestionError,
    DatasetQueryAdapter,
    WarehouseConnectorRegistry,
    WarehouseDatasetAdapter,
    dataset_reference_from_metadata,
    default_warehouse_registry,
)
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.storage import ArtifactStorageError, ArtifactStore, LocalArtifactStore


class AnalyticsCodeAgent:
    agent_type = "analytics_code"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        code_guard: PythonCodeGuard | None = None,
        warehouse_registry: WarehouseConnectorRegistry | None = None,
        warehouse_row_limit: int = 10_000,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store or LocalArtifactStore(artifact_root)
        self._code_guard = code_guard or PythonCodeGuard()
        self._warehouse_registry = warehouse_registry or default_warehouse_registry()
        self._warehouse_row_limit = warehouse_row_limit

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        source_code = agent_input.context.get("analysis_code")
        if source_code is None:
            source_code = generate_reproducible_analysis_code()
        if not isinstance(source_code, str):
            return self._failed_output("Analysis code must be a string.")

        safety_report = self._code_guard.evaluate(source_code)
        if safety_report.decision == CodeSafetyDecision.BLOCKED:
            reasons = [violation.message for violation in safety_report.violations]
            return self._failed_output(
                "Generated analysis code violates the execution policy.",
                errors=reasons,
                safety_report=safety_report.to_dict(),
            )
        if (
            safety_report.decision == CodeSafetyDecision.APPROVAL_REQUIRED
            and "approved" not in agent_input.approvals
        ):
            return AgentOutput(
                status="waiting_for_approval",
                summary="Analysis code requires approval before it can be accepted.",
                events=[
                    {
                        "event_type": AgentEventType.APPROVAL_REQUEST,
                        "message": "Generated code contains approval-required operations.",
                        "safety_report": safety_report.to_dict(),
                    }
                ],
                metrics={"safety_report": safety_report.to_dict()},
            )

        try:
            dataset = self._resolve_dataset_artifact(agent_input)
            adapter, adapter_name = self._build_dataset_adapter(dataset)
            analysis = analyze_procurement_dataset(adapter).to_dict()
            kpi_artifact_id = self._repository.next_artifact_id()
            code_artifact_id = self._repository.next_artifact_id()
            analysis_payload = self._artifact_store.write_json(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="procurement_analysis.json",
                payload=analysis,
            )
            code_payload = self._artifact_store.write_text(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="procurement_analysis.py",
                payload=source_code,
                content_type="text/x-python; charset=utf-8",
            )

            kpi_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.KPI_TABLE,
                artifact_id=kpi_artifact_id,
                uri=analysis_payload.uri,
                metadata={
                    "source": "analytics_code_agent",
                    "format": "json",
                    "total_spend": analysis["kpis"]["total_spend"],
                    "insight_count": len(analysis["insights"]),
                    **analysis_payload.metadata,
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )
            code_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.CODE,
                artifact_id=code_artifact_id,
                uri=code_payload.uri,
                metadata={
                    "source": "analytics_code_agent",
                    "language": "python",
                    "safety_decision": safety_report.decision.value,
                    "execution_mode": "validated_artifact_only",
                    **code_payload.metadata,
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )
        except (AnalyticsError, ArtifactStorageError, DataIngestionError, KeyError, OSError) as exc:
            return self._failed_output(str(exc), safety_report=safety_report.to_dict())

        return AgentOutput(
            status="succeeded",
            summary=(
                f"Analyzed {analysis['dataset']['row_count']} procurement rows with total spend "
                f"{analysis['kpis']['total_spend']}."
            ),
            artifacts=[kpi_artifact.id, code_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Procurement KPIs and reproducible code artifacts registered.",
                    "dataset_artifact_id": dataset.id,
                    "kpi_artifact_id": kpi_artifact.id,
                    "code_artifact_id": code_artifact.id,
                }
            ],
            metrics={
                "total_spend": analysis["kpis"]["total_spend"],
                "supplier_count": analysis["kpis"]["supplier_count"],
                "category_count": analysis["kpis"]["category_count"],
                "outlier_count": analysis["kpis"]["outlier_count"],
                "anomaly_count": analysis["kpis"]["anomaly_count"],
                "high_risk_count": analysis["kpis"]["high_risk_count"],
                "risk_exposure": analysis["kpis"]["risk_exposure"],
                "estimated_savings": analysis["kpis"]["estimated_savings"],
                "adapter": adapter_name,
                "safety_report": safety_report.to_dict(),
            },
        )

    def _build_dataset_adapter(
        self, dataset: ArtifactRecord
    ) -> tuple[DatasetQueryAdapter, str]:
        dataset_reference = dataset_reference_from_metadata(dataset.uri, dataset.metadata)
        if dataset_reference.kind == "warehouse":
            if dataset_reference.warehouse is None:
                raise AnalyticsError("Warehouse dataset reference is missing source details.")
            connector = self._warehouse_registry.connector_for_reference(
                dataset_reference.warehouse
            )
            return (
                WarehouseDatasetAdapter(
                    connector=connector,
                    reference=dataset_reference.warehouse,
                    row_limit=self._warehouse_row_limit,
                ),
                connector.__class__.__name__,
            )
        return (
            CsvDatasetAdapter.from_path(self._artifact_store.local_path(dataset.uri)),
            "CsvDatasetAdapter",
        )

    def _resolve_dataset_artifact(self, agent_input: AgentInput) -> ArtifactRecord:
        artifact_id = (
            agent_input.context.get("dataset_artifact_id")
            or self._repository.get_run(agent_input.run_id).dataset_artifact_id
        )
        if not artifact_id:
            raise AnalyticsError("No dataset artifact is attached to the run.")
        artifact = self._repository.get_artifact(agent_input.run_id, artifact_id)
        if artifact.type != ArtifactType.DATASET:
            raise AnalyticsError(f"Artifact is not a dataset: {artifact_id}")
        return artifact

    @staticmethod
    def _failed_output(
        summary: str,
        errors: list[str] | None = None,
        safety_report: dict[str, Any] | None = None,
    ) -> AgentOutput:
        return AgentOutput(
            status="failed",
            summary=summary,
            errors=list(errors or [summary]),
            events=[
                {
                    "event_type": AgentEventType.ERROR,
                    "message": summary,
                    "safety_report": safety_report,
                }
            ],
            metrics={"safety_report": safety_report} if safety_report else {},
        )

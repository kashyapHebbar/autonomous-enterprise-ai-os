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
from aeai_os.analytics.generic import analyze_generic_dataset
from aeai_os.analytics.reproducible import (
    generate_generic_analysis_code,
    generate_reproducible_analysis_code,
)
from aeai_os.connectors import ConnectorRegistry
from aeai_os.connectors.explorer import ConnectorExplorer
from aeai_os.data import (
    CsvDatasetAdapter,
    DataIngestionError,
    DatasetQueryAdapter,
    WarehouseConnectorRegistry,
    WarehouseDatasetAdapter,
    analysis_plan_from_schema,
    build_dataset_analysis_plan,
    dataset_reference_from_metadata,
    default_warehouse_registry,
    profile_tabular_rows,
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
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store or LocalArtifactStore(artifact_root)
        self._code_guard = code_guard or PythonCodeGuard()
        self._warehouse_registry = warehouse_registry or default_warehouse_registry()
        self._connector_registry = connector_registry
        self._warehouse_row_limit = warehouse_row_limit

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        source_code = agent_input.context.get("analysis_code")
        if source_code is not None and not isinstance(source_code, str):
            return self._failed_output("Analysis code must be a string.")

        try:
            dataset = self._resolve_dataset_artifact(agent_input)
            adapter, adapter_name = self._build_dataset_adapter(dataset)
            analysis_plan = self._resolve_analysis_plan(agent_input, adapter)
            if source_code is None:
                source_code = (
                    generate_reproducible_analysis_code()
                    if analysis_plan.recipe == "procurement"
                    else generate_generic_analysis_code()
                )
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
            analysis = (
                analyze_procurement_dataset(adapter).to_dict()
                if analysis_plan.recipe == "procurement"
                else analyze_generic_dataset(adapter, analysis_plan)
            )
            analysis.setdefault("analysis_type", analysis_plan.recipe)
            analysis.setdefault("analysis_plan", analysis_plan.model_dump())
            kpi_artifact_id = self._repository.next_artifact_id()
            code_artifact_id = self._repository.next_artifact_id()
            analysis_payload = self._artifact_store.write_json(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename=f"{analysis_plan.recipe}_analysis.json",
                payload=analysis,
            )
            code_payload = self._artifact_store.write_text(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename=f"{analysis_plan.recipe}_analysis.py",
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
                    "analysis_type": analysis_plan.recipe,
                    "insight_count": len(analysis["insights"]),
                    **(
                        {"total_spend": analysis["kpis"]["total_spend"]}
                        if analysis_plan.recipe == "procurement"
                        else {"row_count": analysis["kpis"]["row_count"]}
                    ),
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
        except (
            AnalyticsError,
            ArtifactStorageError,
            DataIngestionError,
            KeyError,
            OSError,
            ValueError,
        ) as exc:
            return self._failed_output(str(exc))

        return AgentOutput(
            status="succeeded",
            summary=(
                f"Analyzed {analysis['dataset']['row_count']} rows using the "
                f"{analysis_plan.recipe} recipe."
            ),
            artifacts=[kpi_artifact.id, code_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Governed analytics and reproducible code artifacts registered.",
                    "dataset_artifact_id": dataset.id,
                    "kpi_artifact_id": kpi_artifact.id,
                    "code_artifact_id": code_artifact.id,
                }
            ],
            metrics={
                **analysis["kpis"],
                "analysis_type": analysis_plan.recipe,
                "adapter": adapter_name,
                "safety_report": safety_report.to_dict(),
            },
        )

    def _resolve_analysis_plan(self, agent_input, adapter):
        for artifact in reversed(self._repository.list_artifacts(agent_input.run_id)):
            if artifact.type == ArtifactType.SCHEMA_PROFILE:
                plan = analysis_plan_from_schema(self._artifact_store.read_json(artifact.uri))
                if plan is not None:
                    return plan
        profile = profile_tabular_rows(
            source_path="analysis-source",
            rows=adapter.rows(),
            fieldnames=adapter.columns(),
        )
        preferred = "procurement" if "procurement" in agent_input.task.lower() else None
        return build_dataset_analysis_plan(profile, agent_input.task, preferred_recipe=preferred)

    def _build_dataset_adapter(self, dataset: ArtifactRecord) -> tuple[DatasetQueryAdapter, str]:
        dataset_reference = dataset_reference_from_metadata(dataset.uri, dataset.metadata)
        if dataset_reference.kind == "warehouse":
            if dataset_reference.warehouse is None:
                raise AnalyticsError("Warehouse dataset reference is missing source details.")
            installation_id = str(dataset.metadata.get("installation_id") or "").strip()
            if installation_id and self._connector_registry is not None:
                organization_id = str(dataset.metadata.get("organization_id") or "local-org")
                installation = self._connector_registry.get_installation(
                    installation_id, organization_id
                )
                connector = ConnectorExplorer(
                    self._connector_registry
                ).warehouse_connector(installation)
            else:
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

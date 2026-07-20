from __future__ import annotations

from pathlib import Path

from aeai_os.agents.planner import PlannerAgent, PlannerValidationError
from aeai_os.connectors import ConnectorRegistry
from aeai_os.connectors.explorer import ConnectorExplorer
from aeai_os.data import (
    WarehouseDatasetAdapter,
    dataset_reference_from_metadata,
    default_warehouse_registry,
    profile_csv_dataset,
    profile_tabular_rows,
)
from aeai_os.observability.tracing import start_span, trace_context
from aeai_os.orchestration.service import OrchestrationResult
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.storage import ArtifactStore
from aeai_os.workflows.procurement import build_procurement_orchestrator


class DynamicWorkflowError(RuntimeError):
    pass


def execute_dynamic_workflow(
    repository: InMemoryRunRepository,
    artifact_root: str | Path,
    run_id: str,
    artifact_store: ArtifactStore,
    connector_registry: ConnectorRegistry | None = None,
) -> OrchestrationResult:
    run = repository.get_run(run_id)
    if not run.dataset_artifact_id:
        raise DynamicWorkflowError("A dataset must be attached before automatic analysis.")
    dataset = repository.get_artifact(run.id, run.dataset_artifact_id)
    with trace_context(
        {
            "run.id": run.id,
            "run.trace_id": run.trace_id,
            "workflow.name": "dynamic_analysis",
            "dataset.artifact_id": dataset.id,
        }
    ):
        try:
            with start_span("planner.inspect_dataset"):
                profile = _profile_dataset(
                    dataset.uri,
                    dataset.metadata,
                    artifact_store,
                    connector_registry,
                )
                plan, analysis_plan = PlannerAgent().create_dynamic_plan(
                    run_id=run.id,
                    user_task=run.task,
                    dataset_profile=profile,
                    dataset_artifact_id=dataset.id,
                )
            repository.add_event(_planning_event(run.id, analysis_plan.model_dump()))
            return build_procurement_orchestrator(
                repository,
                artifact_root,
                artifact_store=artifact_store,
                connector_registry=connector_registry,
            ).execute_run(run.id, plan.to_execution_graph())
        except (OSError, ValueError, PlannerValidationError) as exc:
            raise DynamicWorkflowError(str(exc)) from exc


def _profile_dataset(uri, metadata, artifact_store, connector_registry=None):
    reference = dataset_reference_from_metadata(uri, metadata)
    if reference.kind == "warehouse":
        if reference.warehouse is None:
            raise DynamicWorkflowError("Warehouse source details are missing.")
        installation_id = str(metadata.get("installation_id") or "").strip()
        if installation_id and connector_registry is not None:
            organization_id = str(metadata.get("organization_id") or "local-org")
            installation = connector_registry.get_installation(
                installation_id, organization_id
            )
            connector = ConnectorExplorer(connector_registry).warehouse_connector(installation)
        else:
            connector = default_warehouse_registry().connector_for_reference(reference.warehouse)
        adapter = WarehouseDatasetAdapter(connector, reference.warehouse, row_limit=10_000)
        return profile_tabular_rows(uri, adapter.rows(), adapter.columns())
    return profile_csv_dataset(artifact_store.local_path(uri))


def _planning_event(run_id, plan):
    from uuid import uuid4

    from aeai_os.runs.models import AgentEventRecord
    from aeai_os.runs.repository import utc_now
    from aeai_os.schemas.enums import AgentEventType

    return AgentEventRecord(
        id=f"event_{uuid4().hex}",
        run_id=run_id,
        node_id="planner",
        event_type=AgentEventType.LOG.value,
        payload={
            "message": "Planner selected a governed analysis recipe from dataset semantics.",
            "analysis_plan": plan,
        },
        created_at=utc_now(),
    )

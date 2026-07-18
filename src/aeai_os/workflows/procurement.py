from __future__ import annotations

from pathlib import Path

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.agents.evaluation import EvaluationAgent
from aeai_os.agents.planner import PlannerAgent, PlannerValidationError
from aeai_os.agents.registry import build_default_registry
from aeai_os.agents.report import ReportAgent
from aeai_os.agents.visualization import VisualizationAgent
from aeai_os.observability.tracing import start_span, trace_context
from aeai_os.orchestration.service import OrchestrationResult, OrchestratorService
from aeai_os.runs.repository import InMemoryRunRepository, RunNotFoundError
from aeai_os.storage import ArtifactStore, LocalArtifactStore


class ProcurementWorkflowError(RuntimeError):
    pass


def execute_procurement_workflow(
    repository: InMemoryRunRepository,
    artifact_root: str | Path,
    run_id: str,
    artifact_store: ArtifactStore | None = None,
) -> OrchestrationResult:
    try:
        run = repository.get_run(run_id)
    except RunNotFoundError:
        raise

    with trace_context(
        {
            "run.id": run.id,
            "run.trace_id": run.trace_id,
            "workflow.name": "procurement",
            "dataset.artifact_id": run.dataset_artifact_id,
        }
    ):
        with start_span("workflow.procurement.execute"):
            if not run.dataset_artifact_id:
                raise ProcurementWorkflowError(
                    "A dataset artifact must be attached before executing the "
                    "procurement workflow."
                )

            try:
                with start_span("planner.create_execution_graph"):
                    plan = PlannerAgent().create_plan(
                        run_id=run.id,
                        user_task=run.task,
                        dataset_artifact_id=run.dataset_artifact_id,
                    )
            except PlannerValidationError as exc:
                raise ProcurementWorkflowError(str(exc)) from exc

            return build_procurement_orchestrator(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ).execute_run(run.id, plan.to_execution_graph())


def build_procurement_orchestrator(
    repository: InMemoryRunRepository,
    artifact_root: str | Path,
    artifact_store: ArtifactStore | None = None,
) -> OrchestratorService:
    artifact_root = Path(artifact_root)
    artifact_store = artifact_store or LocalArtifactStore(artifact_root)
    return OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={
            "data_retrieval": DataRetrievalAgent(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ),
            "analytics_code": AnalyticsCodeAgent(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ),
            "visualization": VisualizationAgent(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ),
            "report": ReportAgent(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ),
            "evaluation": EvaluationAgent(
                repository,
                artifact_root,
                artifact_store=artifact_store,
            ),
        },
    )

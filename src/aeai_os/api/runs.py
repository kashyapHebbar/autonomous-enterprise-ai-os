from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Body, File, HTTPException, UploadFile, status

from aeai_os.api.auth import RunApprover, RunReader, RunWriter
from aeai_os.api.run_schemas import (
    AgentEventResponse,
    ApprovalDecisionRequest,
    ArtifactLineageResponse,
    ArtifactResponse,
    AttachDatasetReferenceRequest,
    CreateDeploymentRequest,
    CreateRunRequest,
    DeploymentApprovalDecisionRequest,
    EvaluationResponse,
    GraphNodeResponse,
    ImportRunArchiveRequest,
    RunDetailResponse,
    RunExecutionResponse,
    RunResponse,
    RunTimelineItemResponse,
    WorkflowJobResponse,
    agent_event_to_response,
    artifact_lineage_to_response,
    artifact_to_response,
    build_run_timeline,
    evaluation_to_response,
    graph_node_to_response,
    run_to_detail_response,
    run_to_execution_response,
    run_to_response,
    workflow_job_to_response,
)
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.deployments import (
    DeploymentApprovalError,
    decide_deployment_approval,
    request_deployment_approval,
)
from aeai_os.orchestration.service import OrchestrationError, OrchestrationResult
from aeai_os.runs.archive import (
    RunArchiveConflictError,
    RunArchiveError,
    export_run_archive,
    import_run_archive,
)
from aeai_os.runs.models import AgentEventRecord
from aeai_os.runs.repository import (
    ArtifactNotFoundError,
    GraphNodeNotFoundError,
    InMemoryRunRepository,
    RunNotFoundError,
    WorkflowJobNotFoundError,
    utc_now,
)
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.security.auth import AuthenticatedUser
from aeai_os.storage import ArtifactStore
from aeai_os.workflows import (
    ProcurementWorkflowError,
    build_procurement_orchestrator,
    execute_procurement_workflow,
)
from aeai_os.workflows.queue import WorkflowQueueBackend
from aeai_os.workflows.worker import enqueue_procurement_workflow

ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".tsv", ".json", ".parquet"}


def build_runs_router(
    repository: InMemoryRunRepository,
    artifact_root: Path,
    artifact_store: ArtifactStore,
    workflow_queue: WorkflowQueueBackend | None = None,
):
    router = APIRouter(prefix="/runs", tags=["runs"])
    lineage_service = ArtifactLineageService(repository)

    @router.post("", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
    def create_run(
        request: Annotated[CreateRunRequest, Body(...)],
        actor: RunWriter,
    ) -> RunDetailResponse:
        run = repository.create_run(task=request.task, metadata=request.metadata)
        if request.dataset_uri:
            repository.add_artifact(
                run_id=run.id,
                artifact_type=ArtifactType.DATASET,
                uri=request.dataset_uri,
                metadata={"source": "reference", **request.metadata},
            )
            run = repository.get_run(run.id)
        _record_audit_event(
            repository,
            run.id,
            actor,
            action="run.create",
            details={
                "dataset_uri": request.dataset_uri,
                "metadata_keys": sorted(request.metadata),
            },
        )
        return run_to_detail_response(
            run,
            repository.list_artifacts(run.id),
            repository.list_evaluations(run.id),
        )

    @router.get("", response_model=list[RunResponse])
    def list_runs(user: RunReader) -> list[RunResponse]:
        return [run_to_response(run) for run in repository.list_runs()]

    @router.post("/import", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
    def import_run(
        request: Annotated[ImportRunArchiveRequest, Body(...)],
        actor: RunWriter,
    ) -> RunDetailResponse:
        try:
            run = import_run_archive(
                repository,
                request.archive,
                overwrite=request.overwrite,
            )
        except RunArchiveConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except RunArchiveError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _record_audit_event(
            repository,
            run.id,
            actor,
            action="run.import_archive",
            target={"run_id": run.id},
            details={"overwrite": request.overwrite},
        )
        return run_to_detail_response(
            repository.get_run(run.id),
            repository.list_artifacts(run.id),
            repository.list_evaluations(run.id),
        )

    @router.get("/{run_id}/export", response_model=dict[str, Any])
    def export_run(run_id: str, user: RunReader) -> dict[str, Any]:
        _get_run_or_404(repository, run_id)
        return export_run_archive(repository, run_id)

    @router.get("/{run_id}", response_model=RunDetailResponse)
    def get_run(run_id: str, user: RunReader) -> RunDetailResponse:
        run = _get_run_or_404(repository, run_id)
        return run_to_detail_response(
            run,
            repository.list_artifacts(run_id),
            repository.list_evaluations(run_id),
        )

    @router.post("/{run_id}/execute/procurement", response_model=RunExecutionResponse)
    def execute_procurement(run_id: str, actor: RunWriter) -> RunExecutionResponse:
        _get_run_or_404(repository, run_id)
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="run.execute_procurement",
        )
        try:
            result = execute_procurement_workflow(
                repository=repository,
                artifact_root=artifact_root,
                run_id=run_id,
                artifact_store=artifact_store,
            )
        except ProcurementWorkflowError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        run = repository.get_run(run_id)
        return _execution_response(repository, run.id, result)

    @router.post(
        "/{run_id}/execute/procurement/async",
        response_model=WorkflowJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_procurement_execution(run_id: str, actor: RunWriter) -> WorkflowJobResponse:
        run = _get_run_or_404(repository, run_id)
        if not run.dataset_artifact_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A dataset artifact must be attached before enqueueing "
                    "the procurement workflow."
                ),
            )
        job = enqueue_procurement_workflow(
            repository=repository,
            run_id=run_id,
            queue=workflow_queue,
        )
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="workflow.enqueue_procurement",
            target={"run_id": run_id, "workflow_job_id": job.id},
        )
        return workflow_job_to_response(job)

    @router.get("/{run_id}/workflow-jobs", response_model=list[WorkflowJobResponse])
    def list_workflow_jobs(run_id: str, user: RunReader) -> list[WorkflowJobResponse]:
        _get_run_or_404(repository, run_id)
        return [
            workflow_job_to_response(job)
            for job in repository.list_workflow_jobs(run_id=run_id)
        ]

    @router.get(
        "/{run_id}/workflow-jobs/{job_id}",
        response_model=WorkflowJobResponse,
    )
    def get_workflow_job(run_id: str, job_id: str, user: RunReader) -> WorkflowJobResponse:
        _get_run_or_404(repository, run_id)
        try:
            job = repository.get_workflow_job(job_id)
        except WorkflowJobNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        if job.run_id != run_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow job not found for run: {job_id}",
            )
        return workflow_job_to_response(job)

    @router.post(
        "/{run_id}/deployments",
        response_model=WorkflowJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_deployment_request(
        run_id: str,
        request: Annotated[CreateDeploymentRequest, Body(...)],
        actor: RunWriter,
    ) -> WorkflowJobResponse:
        _get_run_or_404(repository, run_id)
        try:
            job = request_deployment_approval(
                repository,
                run_id=run_id,
                artifact_ids=request.artifact_ids,
                destination=request.destination,
                requested_by=request.requested_by,
                rationale=request.rationale,
                metadata=request.metadata,
            )
        except ArtifactNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeploymentApprovalError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="deployment.request",
            target={"run_id": run_id, "workflow_job_id": job.id},
            details={
                "artifact_ids": request.artifact_ids,
                "destination": request.destination,
                "requested_by": request.requested_by,
            },
        )
        return workflow_job_to_response(job)

    @router.post(
        "/{run_id}/deployments/{job_id}/approval",
        response_model=WorkflowJobResponse,
    )
    def decide_deployment_request(
        run_id: str,
        job_id: str,
        request: Annotated[DeploymentApprovalDecisionRequest, Body(...)],
        actor: RunApprover,
    ) -> WorkflowJobResponse:
        _get_run_or_404(repository, run_id)
        try:
            result = decide_deployment_approval(
                repository,
                run_id=run_id,
                job_id=job_id,
                approved=request.approved,
                approver=request.approver,
                rationale=request.rationale,
            )
        except WorkflowJobNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ArtifactNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DeploymentApprovalError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="deployment.approval",
            target={"run_id": run_id, "workflow_job_id": job_id},
            details={
                "approved": request.approved,
                "approver": request.approver,
                "rationale": request.rationale,
            },
        )
        return workflow_job_to_response(result.job)

    @router.get("/{run_id}/graph-nodes", response_model=list[GraphNodeResponse])
    def list_graph_nodes(run_id: str, user: RunReader) -> list[GraphNodeResponse]:
        _get_run_or_404(repository, run_id)
        return [
            graph_node_to_response(node)
            for node in repository.list_graph_nodes(run_id)
        ]

    @router.get("/{run_id}/events", response_model=list[AgentEventResponse])
    def list_events(run_id: str, user: RunReader) -> list[AgentEventResponse]:
        _get_run_or_404(repository, run_id)
        return [
            agent_event_to_response(event)
            for event in repository.list_events(run_id)
        ]

    @router.get("/{run_id}/timeline", response_model=list[RunTimelineItemResponse])
    def get_run_timeline(run_id: str, user: RunReader) -> list[RunTimelineItemResponse]:
        run = _get_run_or_404(repository, run_id)
        return build_run_timeline(
            run=run,
            workflow_jobs=repository.list_workflow_jobs(run_id=run_id),
            graph_nodes=repository.list_graph_nodes(run_id),
            events=repository.list_events(run_id),
            artifacts=repository.list_artifacts(run_id),
            evaluations=repository.list_evaluations(run_id),
        )

    @router.post(
        "/{run_id}/graph-nodes/{node_id}/approval",
        response_model=RunExecutionResponse,
    )
    def decide_graph_node_approval(
        run_id: str,
        node_id: str,
        request: Annotated[ApprovalDecisionRequest, Body(...)],
        actor: RunApprover,
    ) -> RunExecutionResponse:
        _get_run_or_404(repository, run_id)
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="graph_node.approval",
            target={"run_id": run_id, "node_id": node_id},
            details={"approved": request.approved, "comment": request.comment},
        )
        service = build_procurement_orchestrator(
            repository,
            artifact_root,
            artifact_store=artifact_store,
        )
        try:
            result = service.approve_node(
                run_id=run_id,
                node_id=node_id,
                approved=request.approved,
                comment=request.comment,
            )
        except GraphNodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except OrchestrationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return _execution_response(repository, run_id, result)

    @router.post(
        "/{run_id}/graph-nodes/{node_id}/retry",
        response_model=RunExecutionResponse,
    )
    def retry_graph_node(run_id: str, node_id: str, actor: RunWriter) -> RunExecutionResponse:
        _get_run_or_404(repository, run_id)
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="graph_node.retry",
            target={"run_id": run_id, "node_id": node_id},
        )
        service = build_procurement_orchestrator(
            repository,
            artifact_root,
            artifact_store=artifact_store,
        )
        try:
            result = service.retry_failed_node(run_id=run_id, node_id=node_id)
        except GraphNodeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except OrchestrationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        return _execution_response(repository, run_id, result)

    @router.get("/{run_id}/evaluations", response_model=list[EvaluationResponse])
    def list_evaluations(run_id: str, user: RunReader) -> list[EvaluationResponse]:
        _get_run_or_404(repository, run_id)
        return [
            evaluation_to_response(evaluation) for evaluation in repository.list_evaluations(run_id)
        ]

    @router.get("/{run_id}/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(run_id: str, user: RunReader) -> list[ArtifactResponse]:
        _get_run_or_404(repository, run_id)
        return [artifact_to_response(artifact) for artifact in repository.list_artifacts(run_id)]

    @router.get("/{run_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
    def get_artifact(run_id: str, artifact_id: str, user: RunReader) -> ArtifactResponse:
        artifact = _get_artifact_or_404(repository, run_id, artifact_id)
        return artifact_to_response(artifact)

    @router.get(
        "/{run_id}/artifacts/{artifact_id}/lineage",
        response_model=ArtifactLineageResponse,
    )
    def get_artifact_lineage(
        run_id: str,
        artifact_id: str,
        user: RunReader,
    ) -> ArtifactLineageResponse:
        _get_artifact_or_404(repository, run_id, artifact_id)
        lineage = lineage_service.build_lineage(run_id, artifact_id)
        return artifact_lineage_to_response(lineage)

    @router.post(
        "/{run_id}/datasets/reference",
        response_model=ArtifactResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def attach_dataset_reference(
        run_id: str,
        request: Annotated[AttachDatasetReferenceRequest, Body(...)],
        actor: RunWriter,
    ) -> ArtifactResponse:
        _get_run_or_404(repository, run_id)
        artifact = repository.add_artifact(
            run_id=run_id,
            artifact_type=ArtifactType.DATASET,
            uri=request.uri,
            metadata={
                "source": "reference",
                "format": request.format,
                **request.metadata,
            },
        )
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="dataset.attach_reference",
            target={"run_id": run_id, "artifact_id": artifact.id},
            details={
                "uri": request.uri,
                "format": request.format,
                "metadata_keys": sorted(request.metadata),
            },
        )
        return artifact_to_response(artifact)

    @router.post(
        "/{run_id}/datasets/upload",
        response_model=ArtifactResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_dataset(
        run_id: str,
        file: Annotated[UploadFile, File(...)],
        actor: RunWriter,
    ) -> ArtifactResponse:
        _get_run_or_404(repository, run_id)
        filename = _validate_upload_filename(file.filename or "")
        payload = await file.read()
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded dataset is empty.",
            )

        extension = Path(filename).suffix.lower()
        artifact_id = repository.next_artifact_id()
        stored_dataset = artifact_store.write_bytes(
            run_id=run_id,
            node_id="datasets",
            filename=f"{artifact_id}{extension}",
            payload=payload,
            content_type=file.content_type,
            metadata={"source": "upload", "filename": filename},
        )

        artifact = repository.add_artifact(
            run_id=run_id,
            artifact_type=ArtifactType.DATASET,
            artifact_id=artifact_id,
            uri=stored_dataset.uri,
            metadata={
                "source": "upload",
                "filename": filename,
                "content_type": file.content_type,
                "size_bytes": len(payload),
                "format": extension.lstrip("."),
                **stored_dataset.metadata,
            },
        )
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="dataset.upload",
            target={"run_id": run_id, "artifact_id": artifact.id},
            details={
                "filename": filename,
                "content_type": file.content_type,
                "size_bytes": len(payload),
                "format": extension.lstrip("."),
            },
        )
        return artifact_to_response(artifact)

    return router


def _record_audit_event(
    repository: InMemoryRunRepository,
    run_id: str,
    actor: AuthenticatedUser,
    *,
    action: str,
    target: dict[str, str] | None = None,
    details: dict[str, object] | None = None,
) -> AgentEventRecord:
    created_at = utc_now()
    payload: dict[str, object] = {
        "message": f"{actor.id} performed {action}.",
        "audit": True,
        "action": action,
        "actor": actor.to_audit_payload(),
        "target": target or {"run_id": run_id},
        "timestamp": created_at.isoformat(),
    }
    if details:
        payload["details"] = details
    return repository.add_event(
        AgentEventRecord(
            id=f"event_{uuid4().hex}",
            run_id=run_id,
            node_id="api",
            event_type=AgentEventType.AUDIT.value,
            payload=payload,
            created_at=created_at,
        )
    )


def _get_run_or_404(repository: InMemoryRunRepository, run_id: str):
    try:
        return repository.get_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _get_artifact_or_404(
    repository: InMemoryRunRepository,
    run_id: str,
    artifact_id: str,
):
    _get_run_or_404(repository, run_id)
    try:
        return repository.get_artifact(run_id, artifact_id)
    except ArtifactNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _execution_response(
    repository: InMemoryRunRepository,
    run_id: str,
    result: OrchestrationResult,
) -> RunExecutionResponse:
    run = repository.get_run(run_id)
    return run_to_execution_response(
        run=run,
        artifacts=repository.list_artifacts(run_id),
        evaluations=repository.list_evaluations(run_id),
        completed_node_ids=result.completed_node_ids,
        failed_node_ids=result.failed_node_ids,
        waiting_for_approval_node_id=result.waiting_for_approval_node_id,
    )


def _validate_upload_filename(filename: str) -> str:
    safe_name = Path(filename).name.strip()
    if not safe_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded dataset must include a filename.",
        )

    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported dataset file type. Allowed extensions: {allowed}.",
        )

    return safe_name


def allowed_upload_extensions() -> Iterable[str]:
    return sorted(ALLOWED_UPLOAD_EXTENSIONS)

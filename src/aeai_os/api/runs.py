from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Body, File, HTTPException, Response, UploadFile, status

from aeai_os.api.auth import RunApprover, RunReader, RunWriter
from aeai_os.api.run_schemas import (
    AgentEventResponse,
    ApprovalDecisionRequest,
    ArtifactLineageResponse,
    ArtifactResponse,
    AttachDatasetReferenceRequest,
    AuditEventResponse,
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
    WorkflowJobControlRequest,
    WorkflowJobResponse,
    agent_event_to_response,
    artifact_lineage_to_response,
    artifact_to_response,
    audit_event_to_response,
    build_run_timeline,
    evaluation_to_response,
    graph_node_to_response,
    run_to_detail_response,
    run_to_execution_response,
    run_to_response,
    workflow_job_to_response,
)
from aeai_os.artifacts import ArtifactLineageService
from aeai_os.data.sources import (
    DataSourceNotFoundError,
    DataSourceRegistry,
    DataSourceValidationError,
)
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
    WorkflowJobStateError,
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
WorkflowJobControlBody = Annotated[
    WorkflowJobControlRequest,
    Body(default_factory=WorkflowJobControlRequest),
]


def build_runs_router(
    repository: InMemoryRunRepository,
    artifact_root: Path,
    artifact_store: ArtifactStore,
    workflow_queue: WorkflowQueueBackend | None = None,
    workflow_execution_mode: str = "sync",
    procurement_workflow_max_attempts: int = 3,
    data_source_registry: DataSourceRegistry | None = None,
):
    router = APIRouter(prefix="/runs", tags=["runs"])
    lineage_service = ArtifactLineageService(repository)
    primary_execution_mode = workflow_execution_mode.strip().lower()
    if primary_execution_mode not in {"sync", "async"}:
        raise ValueError(
            "workflow_execution_mode must be either 'sync' or 'async'."
        )

    @router.post("", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
    def create_run(
        request: Annotated[CreateRunRequest, Body(...)],
        actor: RunWriter,
    ) -> RunDetailResponse:
        if request.dataset_uri and request.data_source_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use either dataset_uri or data_source_id when creating a run, not both.",
            )
        data_source = None
        if request.data_source_id:
            if data_source_registry is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Data source registry is not configured.",
                )
            try:
                data_source = data_source_registry.validate_for_execution(
                    request.data_source_id
                )
            except DataSourceNotFoundError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=str(exc),
                ) from exc
            except DataSourceValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "status": exc.result.status,
                        "message": exc.result.message,
                        "details": exc.result.details,
                    },
                ) from exc

        run_metadata = dict(request.metadata)
        if data_source is not None:
            run_metadata.update(
                {
                    "data_source_id": data_source.id,
                    "data_source_name": data_source.name,
                    "data_source_type": data_source.source_type,
                    "connector_id": data_source.connector_id,
                    "credential_profile_id": data_source.credential_profile_id,
                }
            )

        run = repository.create_run(task=request.task, metadata=run_metadata)
        if request.dataset_uri:
            repository.add_artifact(
                run_id=run.id,
                artifact_type=ArtifactType.DATASET,
                uri=request.dataset_uri,
                metadata={"source": "reference", **request.metadata},
            )
            run = repository.get_run(run.id)
        if data_source is not None:
            repository.add_artifact(
                run_id=run.id,
                artifact_type=ArtifactType.DATASET,
                uri=data_source.dataset_uri,
                metadata=data_source.dataset_metadata(),
            )
            run = repository.get_run(run.id)
        _record_audit_event(
            repository,
            run.id,
            actor,
            action="run.create",
            details={
                "dataset_uri": request.dataset_uri,
                "data_source_id": request.data_source_id,
                "metadata_keys": sorted(run_metadata),
            },
        )
        return run_to_detail_response(
            run,
            repository.list_artifacts(run.id),
            repository.list_evaluations(run.id),
            repository.list_events(run.id),
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
            repository.list_events(run.id),
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
            repository.list_events(run_id),
        )

    @router.post(
        "/{run_id}/execute/procurement",
        response_model=RunExecutionResponse | WorkflowJobResponse,
    )
    def execute_procurement(
        run_id: str,
        actor: RunWriter,
        response: Response,
    ) -> RunExecutionResponse | WorkflowJobResponse:
        if primary_execution_mode == "async":
            response.status_code = status.HTTP_202_ACCEPTED
            return _enqueue_procurement_or_400(
                repository=repository,
                run_id=run_id,
                actor=actor,
                queue=workflow_queue,
                max_attempts=procurement_workflow_max_attempts,
            )

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
        return _enqueue_procurement_or_400(
            repository=repository,
            run_id=run_id,
            actor=actor,
            queue=workflow_queue,
            max_attempts=procurement_workflow_max_attempts,
        )

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
        "/{run_id}/workflow-jobs/{job_id}/retry",
        response_model=WorkflowJobResponse,
    )
    def retry_dead_letter_workflow_job(
        run_id: str,
        job_id: str,
        request: WorkflowJobControlBody,
        actor: RunWriter,
    ) -> WorkflowJobResponse:
        _get_run_or_404(repository, run_id)
        _get_workflow_job_for_run_or_404(repository, run_id, job_id)
        try:
            if workflow_queue is None:
                job = repository.retry_dead_letter_workflow_job(
                    job_id=job_id,
                    reason=request.reason,
                )
            else:
                job = workflow_queue.retry_dead_letter(
                    job_id=job_id,
                    reason=request.reason,
                )
        except WorkflowJobStateError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="workflow.retry_dead_letter",
            target={"run_id": run_id, "workflow_job_id": job.id},
            details={"reason": request.reason, "attempt_count": job.attempt_count},
        )
        return workflow_job_to_response(job)

    @router.post(
        "/{run_id}/workflow-jobs/{job_id}/dismiss",
        response_model=WorkflowJobResponse,
    )
    def dismiss_dead_letter_workflow_job(
        run_id: str,
        job_id: str,
        request: WorkflowJobControlBody,
        actor: RunWriter,
    ) -> WorkflowJobResponse:
        _get_run_or_404(repository, run_id)
        _get_workflow_job_for_run_or_404(repository, run_id, job_id)
        try:
            if workflow_queue is None:
                job = repository.dismiss_dead_letter_workflow_job(
                    job_id=job_id,
                    reason=request.reason,
                )
            else:
                job = workflow_queue.dismiss_dead_letter(
                    job_id=job_id,
                    reason=request.reason,
                )
        except WorkflowJobStateError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        _record_audit_event(
            repository,
            run_id,
            actor,
            action="workflow.dismiss_dead_letter",
            target={"run_id": run_id, "workflow_job_id": job.id},
            details={"reason": request.reason},
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

    @router.get("/{run_id}/audit-events", response_model=list[AuditEventResponse])
    def list_audit_events(run_id: str, user: RunReader) -> list[AuditEventResponse]:
        _get_run_or_404(repository, run_id)
        return [
            audit_event
            for event in repository.list_events(run_id)
            if (audit_event := audit_event_to_response(event)) is not None
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
    run = repository.get_run(run_id)
    payload: dict[str, object] = {
        "message": f"{actor.id} performed {action}.",
        "audit": True,
        "run_id": run_id,
        "trace_id": run.trace_id,
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


def _enqueue_procurement_or_400(
    *,
    repository: InMemoryRunRepository,
    run_id: str,
    actor: AuthenticatedUser,
    queue: WorkflowQueueBackend | None,
    max_attempts: int,
) -> WorkflowJobResponse:
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
        queue=queue,
        max_attempts=max_attempts,
    )
    _record_audit_event(
        repository,
        run_id,
        actor,
        action="workflow.enqueue_procurement",
        target={"run_id": run_id, "workflow_job_id": job.id},
    )
    return workflow_job_to_response(job)


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


def _get_workflow_job_for_run_or_404(
    repository: InMemoryRunRepository,
    run_id: str,
    job_id: str,
):
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
    return job


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
        events=repository.list_events(run_id),
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

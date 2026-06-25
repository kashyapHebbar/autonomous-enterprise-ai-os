from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, File, HTTPException, UploadFile, status

from aeai_os.api.run_schemas import (
    AgentEventResponse,
    ArtifactLineageResponse,
    ArtifactResponse,
    AttachDatasetReferenceRequest,
    CreateRunRequest,
    EvaluationResponse,
    GraphNodeResponse,
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
from aeai_os.runs.repository import (
    ArtifactNotFoundError,
    InMemoryRunRepository,
    RunNotFoundError,
    WorkflowJobNotFoundError,
)
from aeai_os.schemas.enums import ArtifactType
from aeai_os.workflows import ProcurementWorkflowError, execute_procurement_workflow
from aeai_os.workflows.worker import enqueue_procurement_workflow

ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".tsv", ".json", ".parquet"}


def build_runs_router(repository: InMemoryRunRepository, artifact_root: Path):
    router = APIRouter(prefix="/runs", tags=["runs"])
    lineage_service = ArtifactLineageService(repository)

    @router.post("", response_model=RunDetailResponse, status_code=status.HTTP_201_CREATED)
    def create_run(request: Annotated[CreateRunRequest, Body(...)]) -> RunDetailResponse:
        run = repository.create_run(task=request.task, metadata=request.metadata)
        if request.dataset_uri:
            repository.add_artifact(
                run_id=run.id,
                artifact_type=ArtifactType.DATASET,
                uri=request.dataset_uri,
                metadata={"source": "reference", **request.metadata},
            )
            run = repository.get_run(run.id)
        return run_to_detail_response(
            run,
            repository.list_artifacts(run.id),
            repository.list_evaluations(run.id),
        )

    @router.get("", response_model=list[RunResponse])
    def list_runs() -> list[RunResponse]:
        return [run_to_response(run) for run in repository.list_runs()]

    @router.get("/{run_id}", response_model=RunDetailResponse)
    def get_run(run_id: str) -> RunDetailResponse:
        run = _get_run_or_404(repository, run_id)
        return run_to_detail_response(
            run,
            repository.list_artifacts(run_id),
            repository.list_evaluations(run_id),
        )

    @router.post("/{run_id}/execute/procurement", response_model=RunExecutionResponse)
    def execute_procurement(run_id: str) -> RunExecutionResponse:
        _get_run_or_404(repository, run_id)
        try:
            result = execute_procurement_workflow(
                repository=repository,
                artifact_root=artifact_root,
                run_id=run_id,
            )
        except ProcurementWorkflowError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        run = repository.get_run(run_id)
        return run_to_execution_response(
            run=run,
            artifacts=repository.list_artifacts(run_id),
            evaluations=repository.list_evaluations(run_id),
            completed_node_ids=result.completed_node_ids,
            failed_node_ids=result.failed_node_ids,
            waiting_for_approval_node_id=result.waiting_for_approval_node_id,
        )

    @router.post(
        "/{run_id}/execute/procurement/async",
        response_model=WorkflowJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_procurement_execution(run_id: str) -> WorkflowJobResponse:
        run = _get_run_or_404(repository, run_id)
        if not run.dataset_artifact_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "A dataset artifact must be attached before enqueueing "
                    "the procurement workflow."
                ),
            )
        job = enqueue_procurement_workflow(repository=repository, run_id=run_id)
        return workflow_job_to_response(job)

    @router.get("/{run_id}/workflow-jobs", response_model=list[WorkflowJobResponse])
    def list_workflow_jobs(run_id: str) -> list[WorkflowJobResponse]:
        _get_run_or_404(repository, run_id)
        return [
            workflow_job_to_response(job)
            for job in repository.list_workflow_jobs(run_id=run_id)
        ]

    @router.get(
        "/{run_id}/workflow-jobs/{job_id}",
        response_model=WorkflowJobResponse,
    )
    def get_workflow_job(run_id: str, job_id: str) -> WorkflowJobResponse:
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

    @router.get("/{run_id}/graph-nodes", response_model=list[GraphNodeResponse])
    def list_graph_nodes(run_id: str) -> list[GraphNodeResponse]:
        _get_run_or_404(repository, run_id)
        return [
            graph_node_to_response(node)
            for node in repository.list_graph_nodes(run_id)
        ]

    @router.get("/{run_id}/events", response_model=list[AgentEventResponse])
    def list_events(run_id: str) -> list[AgentEventResponse]:
        _get_run_or_404(repository, run_id)
        return [
            agent_event_to_response(event)
            for event in repository.list_events(run_id)
        ]

    @router.get("/{run_id}/timeline", response_model=list[RunTimelineItemResponse])
    def get_run_timeline(run_id: str) -> list[RunTimelineItemResponse]:
        run = _get_run_or_404(repository, run_id)
        return build_run_timeline(
            run=run,
            workflow_jobs=repository.list_workflow_jobs(run_id=run_id),
            graph_nodes=repository.list_graph_nodes(run_id),
            events=repository.list_events(run_id),
            artifacts=repository.list_artifacts(run_id),
            evaluations=repository.list_evaluations(run_id),
        )

    @router.get("/{run_id}/evaluations", response_model=list[EvaluationResponse])
    def list_evaluations(run_id: str) -> list[EvaluationResponse]:
        _get_run_or_404(repository, run_id)
        return [
            evaluation_to_response(evaluation) for evaluation in repository.list_evaluations(run_id)
        ]

    @router.get("/{run_id}/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(run_id: str) -> list[ArtifactResponse]:
        _get_run_or_404(repository, run_id)
        return [artifact_to_response(artifact) for artifact in repository.list_artifacts(run_id)]

    @router.get("/{run_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
    def get_artifact(run_id: str, artifact_id: str) -> ArtifactResponse:
        artifact = _get_artifact_or_404(repository, run_id, artifact_id)
        return artifact_to_response(artifact)

    @router.get(
        "/{run_id}/artifacts/{artifact_id}/lineage",
        response_model=ArtifactLineageResponse,
    )
    def get_artifact_lineage(run_id: str, artifact_id: str) -> ArtifactLineageResponse:
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
        return artifact_to_response(artifact)

    @router.post(
        "/{run_id}/datasets/upload",
        response_model=ArtifactResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_dataset(
        run_id: str,
        file: Annotated[UploadFile, File(...)],
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
        run_dir = artifact_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        local_path = run_dir / f"{artifact_id}{extension}"
        local_path.write_bytes(payload)

        artifact = repository.add_artifact(
            run_id=run_id,
            artifact_type=ArtifactType.DATASET,
            artifact_id=artifact_id,
            uri=str(local_path),
            metadata={
                "source": "upload",
                "filename": filename,
                "content_type": file.content_type,
                "size_bytes": len(payload),
                "format": extension.lstrip("."),
            },
        )
        return artifact_to_response(artifact)

    return router


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

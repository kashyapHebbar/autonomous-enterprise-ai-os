from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, File, HTTPException, UploadFile, status

from aeai_os.api.run_schemas import (
    ArtifactResponse,
    AttachDatasetReferenceRequest,
    CreateRunRequest,
    RunDetailResponse,
    RunResponse,
    artifact_to_response,
    run_to_detail_response,
    run_to_response,
)
from aeai_os.runs.repository import InMemoryRunRepository, RunNotFoundError
from aeai_os.schemas.enums import ArtifactType

ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".tsv", ".json", ".parquet"}


def build_runs_router(repository: InMemoryRunRepository, artifact_root: Path):
    router = APIRouter(prefix="/runs", tags=["runs"])

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
        return run_to_detail_response(run, repository.list_artifacts(run.id))

    @router.get("", response_model=list[RunResponse])
    def list_runs() -> list[RunResponse]:
        return [run_to_response(run) for run in repository.list_runs()]

    @router.get("/{run_id}", response_model=RunDetailResponse)
    def get_run(run_id: str) -> RunDetailResponse:
        run = _get_run_or_404(repository, run_id)
        return run_to_detail_response(run, repository.list_artifacts(run_id))

    @router.get("/{run_id}/artifacts", response_model=list[ArtifactResponse])
    def list_artifacts(run_id: str) -> list[ArtifactResponse]:
        _get_run_or_404(repository, run_id)
        return [artifact_to_response(artifact) for artifact in repository.list_artifacts(run_id)]

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

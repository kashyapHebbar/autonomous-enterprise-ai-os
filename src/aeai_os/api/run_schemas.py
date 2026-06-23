from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from aeai_os.artifacts import ArtifactLineage
from aeai_os.runs.models import ArtifactRecord, EvaluationResultRecord, RunRecord
from aeai_os.schemas.enums import ArtifactType, RunStatus


class CreateRunRequest(BaseModel):
    task: str = Field(..., max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dataset_uri: str | None = Field(default=None, max_length=2048)

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Task must contain at least 3 non-whitespace characters.")
        return normalized


class AttachDatasetReferenceRequest(BaseModel):
    uri: str = Field(..., max_length=2048)
    format: str = Field(default="csv", max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Dataset URI is required.")
        return normalized

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"csv", "tsv", "parquet", "json"}:
            raise ValueError("Dataset format must be one of: csv, tsv, parquet, json.")
        return normalized


class ArtifactResponse(BaseModel):
    id: str
    run_id: str
    producer_node_id: str | None
    type: ArtifactType
    uri: str
    metadata: dict[str, Any]
    source_artifact_ids: list[str]
    created_at: datetime


class ArtifactLineageEdgeResponse(BaseModel):
    source_artifact_id: str
    target_artifact_id: str


class ArtifactLineageResponse(BaseModel):
    root_artifact: ArtifactResponse
    upstream_artifacts: list[ArtifactResponse]
    edges: list[ArtifactLineageEdgeResponse]


class EvaluationResponse(BaseModel):
    id: str
    run_id: str
    target_artifact_id: str | None
    score: float
    passed: bool
    checks: list[dict[str, Any]]
    created_at: datetime


class RunResponse(BaseModel):
    id: str
    task: str
    status: RunStatus
    metadata: dict[str, Any]
    dataset_artifact_id: str | None
    created_at: datetime
    updated_at: datetime
    trace_id: str | None
    error_summary: str | None


class RunDetailResponse(RunResponse):
    artifacts: list[ArtifactResponse]
    evaluations: list[EvaluationResponse]


def artifact_to_response(artifact: ArtifactRecord) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        run_id=artifact.run_id,
        producer_node_id=artifact.producer_node_id,
        type=artifact.type,
        uri=artifact.uri,
        metadata=artifact.metadata,
        source_artifact_ids=artifact.source_artifact_ids,
        created_at=artifact.created_at,
    )


def artifact_lineage_to_response(lineage: ArtifactLineage) -> ArtifactLineageResponse:
    return ArtifactLineageResponse(
        root_artifact=artifact_to_response(lineage.root_artifact),
        upstream_artifacts=[
            artifact_to_response(artifact) for artifact in lineage.upstream_artifacts
        ],
        edges=[
            ArtifactLineageEdgeResponse(
                source_artifact_id=edge.source_artifact_id,
                target_artifact_id=edge.target_artifact_id,
            )
            for edge in lineage.edges
        ],
    )


def evaluation_to_response(evaluation: EvaluationResultRecord) -> EvaluationResponse:
    if evaluation.created_at is None:
        raise ValueError(f"Evaluation record is missing created_at: {evaluation.id}")
    return EvaluationResponse(
        id=evaluation.id,
        run_id=evaluation.run_id,
        target_artifact_id=evaluation.target_artifact_id,
        score=evaluation.score,
        passed=evaluation.passed,
        checks=evaluation.checks,
        created_at=evaluation.created_at,
    )


def run_to_response(run: RunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        task=run.task,
        status=run.status,
        metadata=run.metadata,
        dataset_artifact_id=run.dataset_artifact_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        trace_id=run.trace_id,
        error_summary=run.error_summary,
    )


def run_to_detail_response(
    run: RunRecord,
    artifacts: list[ArtifactRecord],
    evaluations: list[EvaluationResultRecord] | None = None,
) -> RunDetailResponse:
    base = run_to_response(run)
    return RunDetailResponse(
        **base.model_dump(),
        artifacts=[artifact_to_response(artifact) for artifact in artifacts],
        evaluations=[evaluation_to_response(evaluation) for evaluation in evaluations or []],
    )

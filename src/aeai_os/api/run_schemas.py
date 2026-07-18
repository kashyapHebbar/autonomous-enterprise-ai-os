from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from aeai_os.artifacts import ArtifactLineage
from aeai_os.runs.models import (
    AgentEventRecord,
    ArtifactRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
    RunRecord,
    WorkflowJobRecord,
)
from aeai_os.schemas.enums import ArtifactType, GraphNodeStatus, RunStatus, WorkflowJobStatus
from aeai_os.security.redaction import redact_text, redact_uri, redact_value


class CreateRunRequest(BaseModel):
    task: str = Field(..., max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dataset_uri: str | None = Field(default=None, max_length=2048)
    data_source_id: str | None = Field(default=None, max_length=100)

    @field_validator("task")
    @classmethod
    def validate_task(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Task must contain at least 3 non-whitespace characters.")
        return normalized

    @field_validator("data_source_id")
    @classmethod
    def validate_data_source_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ImportRunArchiveRequest(BaseModel):
    archive: dict[str, Any] = Field(...)
    overwrite: bool = False


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
        supported = {"csv", "tsv", "parquet", "json", "sqlite", "snowflake", "warehouse"}
        if normalized not in supported:
            raise ValueError(
                "Dataset format must be one of: csv, tsv, parquet, json, sqlite, "
                "snowflake, warehouse."
            )
        return normalized


class ApprovalDecisionRequest(BaseModel):
    approved: bool = True
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CreateDeploymentRequest(BaseModel):
    artifact_ids: list[str] = Field(..., min_length=1, max_length=50)
    destination: str = Field(..., max_length=512)
    requested_by: str | None = Field(default=None, max_length=200)
    rationale: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("artifact_ids")
    @classmethod
    def validate_artifact_ids(cls, value: list[str]) -> list[str]:
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for artifact_id in value:
            normalized = artifact_id.strip()
            if normalized and normalized not in seen:
                normalized_ids.append(normalized)
                seen.add(normalized)
        if not normalized_ids:
            raise ValueError("At least one artifact ID is required.")
        return normalized_ids

    @field_validator("destination")
    @classmethod
    def validate_destination(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Deployment destination is required.")
        return normalized

    @field_validator("requested_by", "rationale")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DeploymentApprovalDecisionRequest(BaseModel):
    approved: bool = True
    approver: str = Field(..., max_length=200)
    rationale: str | None = Field(default=None, max_length=1000)

    @field_validator("approver")
    @classmethod
    def validate_approver(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Deployment approver is required.")
        return normalized

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkflowJobControlRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ArtifactResponse(BaseModel):
    id: str
    run_id: str
    producer_node_id: str | None
    type: ArtifactType
    uri: str
    metadata: dict[str, Any]
    content_type: str | None
    storage_backend: str | None
    storage_key: str | None
    size_bytes: int | None
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


class GraphNodeResponse(BaseModel):
    id: str
    run_id: str
    agent_type: str
    status: GraphNodeStatus
    depends_on: list[str]
    required_tools: list[str]
    expected_artifacts: list[str]
    retry_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentEventResponse(BaseModel):
    id: str
    run_id: str
    node_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class AuditEventResponse(BaseModel):
    id: str
    run_id: str
    trace_id: str | None
    action: str
    actor: dict[str, Any]
    target: dict[str, Any]
    details: dict[str, Any]
    timestamp: datetime
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
    audit_events: list[AuditEventResponse] = Field(default_factory=list)


class RunExecutionResponse(RunDetailResponse):
    completed_node_ids: list[str]
    failed_node_ids: list[str]
    waiting_for_approval_node_id: str | None


class WorkflowJobResponse(BaseModel):
    id: str
    run_id: str
    workflow_name: str
    status: WorkflowJobStatus
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    worker_id: str | None
    error_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RunTimelineItemResponse(BaseModel):
    timestamp: datetime
    kind: str
    title: str
    status: str | None = None
    summary: str | None = None
    run_id: str
    node_id: str | None = None
    artifact_id: str | None = None
    evaluation_id: str | None = None
    workflow_job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def artifact_to_response(artifact: ArtifactRecord) -> ArtifactResponse:
    return ArtifactResponse(
        id=artifact.id,
        run_id=artifact.run_id,
        producer_node_id=artifact.producer_node_id,
        type=artifact.type,
        uri=redact_uri(artifact.uri),
        metadata=redact_value(artifact.metadata),
        content_type=artifact.content_type,
        storage_backend=artifact.storage_backend,
        storage_key=redact_uri(artifact.storage_key) if artifact.storage_key else None,
        size_bytes=artifact.size_bytes,
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
        checks=redact_value(evaluation.checks),
        created_at=evaluation.created_at,
    )


def graph_node_to_response(node: GraphNodeRecord) -> GraphNodeResponse:
    return GraphNodeResponse(
        id=node.id,
        run_id=node.run_id,
        agent_type=node.agent_type,
        status=node.status,
        depends_on=node.depends_on,
        required_tools=node.required_tools,
        expected_artifacts=node.expected_artifacts,
        retry_count=node.retry_count,
        started_at=node.started_at,
        finished_at=node.finished_at,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def agent_event_to_response(event: AgentEventRecord) -> AgentEventResponse:
    return AgentEventResponse(
        id=event.id,
        run_id=event.run_id,
        node_id=event.node_id,
        event_type=event.event_type,
        payload=redact_value(event.payload),
        created_at=event.created_at,
    )


def audit_event_to_response(event: AgentEventRecord) -> AuditEventResponse | None:
    if event.event_type != "audit" or not event.payload.get("audit"):
        return None
    timestamp = event.payload.get("timestamp")
    if isinstance(timestamp, datetime):
        parsed_timestamp = timestamp
    elif isinstance(timestamp, str):
        parsed_timestamp = datetime.fromisoformat(timestamp)
    else:
        parsed_timestamp = event.created_at
    return AuditEventResponse(
        id=event.id,
        run_id=str(event.payload.get("run_id") or event.run_id),
        trace_id=event.payload.get("trace_id"),
        action=str(event.payload.get("action") or "unknown"),
        actor=redact_value(dict(event.payload.get("actor") or {})),
        target=redact_value(dict(event.payload.get("target") or {})),
        details=redact_value(dict(event.payload.get("details") or {})),
        timestamp=parsed_timestamp,
        created_at=event.created_at,
    )


def run_to_response(run: RunRecord) -> RunResponse:
    return RunResponse(
        id=run.id,
        task=redact_text(run.task) or "",
        status=run.status,
        metadata=redact_value(run.metadata),
        dataset_artifact_id=run.dataset_artifact_id,
        created_at=run.created_at,
        updated_at=run.updated_at,
        trace_id=run.trace_id,
        error_summary=redact_text(run.error_summary),
    )


def run_to_detail_response(
    run: RunRecord,
    artifacts: list[ArtifactRecord],
    evaluations: list[EvaluationResultRecord] | None = None,
    events: list[AgentEventRecord] | None = None,
) -> RunDetailResponse:
    base = run_to_response(run)
    audit_events = [
        audit_event
        for event in events or []
        if (audit_event := audit_event_to_response(event)) is not None
    ]
    return RunDetailResponse(
        **base.model_dump(),
        artifacts=[artifact_to_response(artifact) for artifact in artifacts],
        evaluations=[evaluation_to_response(evaluation) for evaluation in evaluations or []],
        audit_events=audit_events,
    )


def run_to_execution_response(
    run: RunRecord,
    artifacts: list[ArtifactRecord],
    evaluations: list[EvaluationResultRecord],
    events: list[AgentEventRecord],
    completed_node_ids: list[str],
    failed_node_ids: list[str],
    waiting_for_approval_node_id: str | None,
) -> RunExecutionResponse:
    detail = run_to_detail_response(run, artifacts, evaluations, events)
    return RunExecutionResponse(
        **detail.model_dump(),
        completed_node_ids=completed_node_ids,
        failed_node_ids=failed_node_ids,
        waiting_for_approval_node_id=waiting_for_approval_node_id,
    )


def workflow_job_to_response(job: WorkflowJobRecord) -> WorkflowJobResponse:
    return WorkflowJobResponse(
        id=job.id,
        run_id=job.run_id,
        workflow_name=job.workflow_name,
        status=job.status,
        payload=redact_value(job.payload),
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        worker_id=job.worker_id,
        error_summary=redact_text(job.error_summary),
        started_at=job.started_at,
        finished_at=job.finished_at,
        heartbeat_at=job.heartbeat_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def build_run_timeline(
    run: RunRecord,
    workflow_jobs: list[WorkflowJobRecord],
    graph_nodes: list[GraphNodeRecord],
    events: list[AgentEventRecord],
    artifacts: list[ArtifactRecord],
    evaluations: list[EvaluationResultRecord],
) -> list[RunTimelineItemResponse]:
    items: list[RunTimelineItemResponse] = [
        RunTimelineItemResponse(
            timestamp=run.created_at,
            kind="run",
            title="Run created",
            status=run.status.value,
            summary=redact_text(run.task),
            run_id=run.id,
            payload={"trace_id": run.trace_id, "metadata": redact_value(run.metadata)},
        )
    ]

    for job in workflow_jobs:
        items.append(
            RunTimelineItemResponse(
                timestamp=job.created_at,
                kind="workflow_job",
                title=f"{job.workflow_name} workflow queued",
                status=job.status.value,
                summary=redact_text(job.error_summary),
                run_id=job.run_id,
                workflow_job_id=job.id,
                payload={
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "worker_id": job.worker_id,
                    "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
                    "job_payload": redact_value(job.payload),
                },
            )
        )
        if job.started_at:
            items.append(
                RunTimelineItemResponse(
                    timestamp=job.started_at,
                kind="workflow_job",
                title=f"{job.workflow_name} workflow claimed",
                status=WorkflowJobStatus.RUNNING.value,
                summary=redact_text(job.worker_id),
                    run_id=job.run_id,
                    workflow_job_id=job.id,
                    payload={"attempt_count": job.attempt_count},
                )
            )
        if job.finished_at:
            items.append(
                RunTimelineItemResponse(
                    timestamp=job.finished_at,
                kind="workflow_job",
                title=f"{job.workflow_name} workflow finished",
                status=job.status.value,
                summary=redact_text(job.error_summary),
                    run_id=job.run_id,
                    workflow_job_id=job.id,
                    payload={"attempt_count": job.attempt_count},
                )
            )

    for node in graph_nodes:
        items.append(
            RunTimelineItemResponse(
                timestamp=node.updated_at,
                kind="graph_node",
                title=f"{node.agent_type} node {node.id}",
                status=node.status.value,
                summary=", ".join(node.expected_artifacts),
                run_id=node.run_id,
                node_id=node.id,
                payload={
                    "depends_on": node.depends_on,
                    "required_tools": node.required_tools,
                    "retry_count": node.retry_count,
                },
            )
        )

    for event in events:
        event_payload = redact_value(event.payload)
        message = event_payload.get("message")
        items.append(
            RunTimelineItemResponse(
                timestamp=event.created_at,
                kind="agent_event",
                title=f"{event.event_type} event",
                status=event.event_type,
                summary=str(message) if message else event.node_id,
                run_id=event.run_id,
                node_id=event.node_id,
                payload=event_payload,
            )
        )

    for artifact in artifacts:
        items.append(
            RunTimelineItemResponse(
                timestamp=artifact.created_at,
                kind="artifact",
                title=f"{artifact.type.value} artifact",
                status=artifact.type.value,
                summary=redact_uri(artifact.uri),
                run_id=artifact.run_id,
                node_id=artifact.producer_node_id,
                artifact_id=artifact.id,
                payload={
                    "metadata": redact_value(artifact.metadata),
                    "source_artifact_ids": artifact.source_artifact_ids,
                },
            )
        )

    for evaluation in evaluations:
        if evaluation.created_at is None:
            continue
        items.append(
            RunTimelineItemResponse(
                timestamp=evaluation.created_at,
                kind="evaluation",
                title="Evaluation result",
                status="passed" if evaluation.passed else "failed",
                summary=f"score={evaluation.score}",
                run_id=evaluation.run_id,
                evaluation_id=evaluation.id,
                artifact_id=evaluation.target_artifact_id,
                payload={"checks": redact_value(evaluation.checks)},
            )
        )

    return sorted(items, key=lambda item: (item.timestamp, item.kind, item.title))

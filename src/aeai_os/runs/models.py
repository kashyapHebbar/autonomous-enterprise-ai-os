from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aeai_os.schemas.enums import ArtifactType, GraphNodeStatus, RunStatus, WorkflowJobStatus


@dataclass(frozen=True)
class RunRecord:
    id: str
    task: str
    status: RunStatus
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    dataset_artifact_id: str | None = None
    trace_id: str | None = None
    error_summary: str | None = None


@dataclass(frozen=True)
class WorkflowJobRecord:
    id: str
    run_id: str
    workflow_name: str
    status: WorkflowJobStatus
    payload: dict[str, Any]
    attempt_count: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    worker_id: str | None = None
    error_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None


@dataclass(frozen=True)
class GraphNodeRecord:
    id: str
    run_id: str
    agent_type: str
    status: GraphNodeStatus
    depends_on: list[str]
    required_tools: list[str]
    expected_artifacts: list[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    run_id: str
    type: ArtifactType
    uri: str
    metadata: dict[str, Any]
    source_artifact_ids: list[str]
    created_at: datetime
    producer_node_id: str | None = None


@dataclass(frozen=True)
class AgentEventRecord:
    id: str
    run_id: str
    node_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class EvaluationResultRecord:
    id: str
    run_id: str
    score: float
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None
    target_artifact_id: str | None = None


@dataclass(frozen=True)
class RunCheckpointRecord:
    run_id: str
    state: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime

from __future__ import annotations

from enum import StrEnum


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"
    DISMISSED = "dismissed"


class GraphNodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ArtifactType(StrEnum):
    DATASET = "dataset"
    SCHEMA_PROFILE = "schema_profile"
    QUALITY_REPORT = "quality_report"
    KPI_TABLE = "kpi_table"
    CHART = "chart"
    DASHBOARD = "dashboard"
    REPORT = "report"
    CODE = "code"
    EVALUATION = "evaluation"
    DEPLOYMENT = "deployment"


class AgentEventType(StrEnum):
    AUDIT = "audit"
    TOOL_CALL = "tool_call"
    LOG = "log"
    EVALUATION = "evaluation"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_DECISION = "approval_decision"
    ERROR = "error"

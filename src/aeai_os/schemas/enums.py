from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactType(str, Enum):
    DATASET = "dataset"
    SCHEMA_PROFILE = "schema_profile"
    QUALITY_REPORT = "quality_report"
    KPI_TABLE = "kpi_table"
    CHART = "chart"
    DASHBOARD = "dashboard"
    REPORT = "report"
    CODE = "code"
    EVALUATION = "evaluation"


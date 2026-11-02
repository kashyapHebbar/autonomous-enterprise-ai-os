"""Tenant-scoped monitoring control plane. No execution in HTTP handlers."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from aeai_os.api.auth import RunReader, RunWriter
from aeai_os.data.sources import (
    DataSourceNotFoundError,
    DataSourceRegistry,
    DataSourceValidationError,
)
from aeai_os.monitoring.store import ALERT_STATES, INTERVALS, MonitorStore


class CreateMonitorRequest(BaseModel):
    name: str = Field(min_length=3, max_length=100)
    task: str = Field(min_length=10, max_length=1500)
    source_id: str = Field(min_length=3, max_length=512)
    interval: str = "daily"
    only_on_change: bool = True
    ai_escalation: bool = False
    anomaly_limit: int = Field(default=1, ge=1, le=100000)
    spend_change_pct: float = Field(default=20, ge=1, le=500)
    minimum_completeness: float = Field(default=0.95, ge=0, le=1)

    @field_validator("interval")
    @classmethod
    def check_interval(cls, value: str) -> str:
        if value not in INTERVALS:
            raise ValueError("Frequency must be hourly, daily or weekly")
        return value

    @field_validator("name", "task", "source_id")
    @classmethod
    def no_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("A non-blank value is required")
        return text


class EnabledBody(BaseModel):
    enabled: bool


class AlertStateBody(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def valid(cls, value: str) -> str:
        if value not in ALERT_STATES:
            raise ValueError("Status must be open, acknowledged, or resolved")
        return value


def build_monitoring_router(store: MonitorStore, sources: DataSourceRegistry) -> APIRouter:
    router = APIRouter(prefix="/monitoring", tags=["monitoring"])

    def owned(monitor_id: str, actor):
        result = store.get(monitor_id, actor.organization_id, actor.workspace_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Monitor not found in this workspace")
        return result

    @router.get("/summary")
    def summary(actor: RunReader):
        return store.summary(actor.organization_id, actor.workspace_id)

    @router.get("/monitors")
    def monitors(actor: RunReader):
        return store.list(actor.organization_id, actor.workspace_id)

    @router.post("/monitors", status_code=201)
    def create(body: CreateMonitorRequest, actor: RunWriter):
        if body.source_id.startswith("s3://"):
            from aeai_os.monitoring.engine import allowed_s3_reference

            try:
                allowed_s3_reference(body.source_id)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail="S3 source must be a CSV/TSV object in an explicitly allowlisted bucket",
                ) from None
            source_id = body.source_id
        else:
            try:
                source = sources.validate_for_execution(
                    body.source_id, actor.organization_id, actor.workspace_id
                )
            except DataSourceNotFoundError:
                raise HTTPException(
                    status_code=404, detail="Data source is not registered in this workspace"
                ) from None
            except DataSourceValidationError:
                raise HTTPException(
                    status_code=422, detail="Registered data source is not currently accessible"
                ) from None
            if source.source_type != "local_file" or not source.dataset_uri.lower().endswith(
                (".csv", ".tsv")
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Scheduled monitoring currently supports registered CSV/TSV or allowlisted S3 sources.",  # noqa: E501
                )
            source_id = source.id
        # Never accept URLs, credentials, paths or arbitrary SQL in monitor records.
        if body.ai_escalation and os.getenv(
            "AEAI_MONITOR_AI_ESCALATION_ENABLED", ""
        ).lower() not in {"true", "1", "yes"}:
            raise HTTPException(
                status_code=422,
                detail="AI escalation requires explicit AEAI_MONITOR_AI_ESCALATION_ENABLED=true on server and worker.",  # noqa: E501
            )
        try:
            return store.create(
                organization_id=actor.organization_id,
                workspace_id=actor.workspace_id,
                name=body.name,
                task=body.task,
                source_id=source_id,
                interval=body.interval,
                only_on_change=body.only_on_change,
                ai_escalation=body.ai_escalation,
                anomaly_limit=body.anomaly_limit,
                spend_change_pct=body.spend_change_pct,
                minimum_completeness=body.minimum_completeness,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.patch("/monitors/{monitor_id}/enabled")
    def enabled(monitor_id: str, body: EnabledBody, actor: RunWriter):
        owned(monitor_id, actor)
        store.set_enabled(monitor_id, actor.organization_id, actor.workspace_id, body.enabled)
        return owned(monitor_id, actor)

    @router.post("/monitors/{monitor_id}/run-now", status_code=202)
    def run_now(monitor_id: str, actor: RunWriter):
        monitor = owned(monitor_id, actor)
        if not monitor["enabled"]:
            raise HTTPException(
                status_code=409, detail="Enable this monitor before scheduling a check"
            )
        store.trigger(monitor_id, actor.organization_id, actor.workspace_id)
        return {
            "queued": True,
            "message": "Scheduled for the external monitoring worker. No model call has been made.",
        }

    @router.get("/monitors/{monitor_id}/history")
    def history(monitor_id: str, actor: RunReader):
        owned(monitor_id, actor)
        return store.history(monitor_id, actor.organization_id, actor.workspace_id)

    @router.get("/alerts")
    def alerts(actor: RunReader, status: str | None = None):
        try:
            return store.alerts(actor.organization_id, actor.workspace_id, state=status)
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown alert status") from None

    @router.patch("/alerts/{alert_id}")
    def update_alert(alert_id: str, body: AlertStateBody, actor: RunWriter):
        if not store.update_alert(alert_id, actor.organization_id, actor.workspace_id, body.status):
            raise HTTPException(status_code=404, detail="Alert not found in this workspace")
        return {"id": alert_id, "status": body.status}

    return router

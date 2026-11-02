"""Workspace-scoped, read-only financial aggregation for registered local CSV runs."""

from __future__ import annotations

from threading import BoundedSemaphore
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from aeai_os.api.auth import RunReader, RunWriter
from aeai_os.runs.models import AgentEventRecord
from aeai_os.runs.repository import utc_now
from aeai_os.scaling.risk import latest_scan, set_scan_action, start_scan
from aeai_os.scaling.summary import ScalingError, stream_financial_summary
from aeai_os.schemas.enums import AgentEventType

_scan_capacity = BoundedSemaphore(1)


def build_scaling_router(repository, artifact_store) -> APIRouter:
    router = APIRouter(prefix="/scaling", tags=["scalable-analytics"])

    def visible(run_id, actor):
        try:
            run = repository.get_run(run_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "Investigation not found.") from None
        if not actor.can_access(
            run.metadata.get("organization_id", "local-org"),
            run.metadata.get("workspace_id", "default"),
        ):
            raise HTTPException(404, "Investigation not found.")
        return run

    @router.get("/runs/{run_id}/financial-overview")
    def saved_overview(run_id: str, actor: RunReader):
        visible(run_id, actor)
        for event in reversed(repository.list_events(run_id)):
            summary = event.payload.get("scaling_financial_overview")
            if isinstance(summary, dict):
                return {"run_id": run_id, **summary}
        return {"run_id": run_id, "status": "not_scanned"}

    @router.post("/runs/{run_id}/financial-overview")
    def compute_overview(run_id: str, actor: RunWriter):
        run = visible(run_id, actor)
        if not run.dataset_artifact_id:
            raise HTTPException(422, "Attach a local CSV dataset first.")
        try:
            dataset = repository.get_artifact(run_id, run.dataset_artifact_id)
            if urlparse(dataset.uri).scheme not in ("", "file"):
                raise ScalingError("This overview currently supports local CSVs only.")
            path = artifact_store.local_path(dataset.uri)
            if not _scan_capacity.acquire(blocking=False):
                raise HTTPException(
                    429, "A financial scan is already running; retry after it completes."
                )
            try:
                summary = stream_financial_summary(path)
            finally:
                _scan_capacity.release()
        except (ScalingError, OSError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from None
        repository.add_event(
            AgentEventRecord(
                id=f"event_{uuid4().hex}",
                run_id=run_id,
                node_id="scalable_financial_overview",
                event_type=AgentEventType.LOG.value,
                created_at=utc_now(),
                payload={
                    "message": "Independent streaming financial overview completed.",
                    "scaling_financial_overview": summary,
                },
            )
        )
        return {"run_id": run_id, **summary}

    @router.get("/runs/{run_id}/risk-scan")
    def read_risk_scan(run_id: str, actor: RunReader):
        visible(run_id, actor)
        return latest_scan(run_id, actor.organization_id, actor.workspace_id) or {
            "status": "not_started",
            "run_id": run_id,
        }

    @router.post("/runs/{run_id}/risk-scan", status_code=202)
    def create_risk_scan(run_id: str, actor: RunWriter):
        run = visible(run_id, actor)
        if not run.dataset_artifact_id:
            raise HTTPException(422, "Attach a local CSV dataset first.")
        try:
            dataset = repository.get_artifact(run_id, run.dataset_artifact_id)
            if urlparse(dataset.uri).scheme not in ("", "file"):
                raise ScalingError("Risk screening supports registered local CSV files only.")
            path = artifact_store.local_path(dataset.uri)
            return start_scan(run_id, path, actor.organization_id, actor.workspace_id)
        except (ScalingError, ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from None

    @router.post("/runs/{run_id}/risk-scan/{scan_id}/cancel")
    def cancel_risk_scan(run_id: str, scan_id: str, actor: RunWriter):
        visible(run_id, actor)
        try:
            return set_scan_action(
                run_id, scan_id, actor.organization_id, actor.workspace_id, "cancel"
            )
        except KeyError:
            raise HTTPException(404, "Risk scan not found.") from None
        except (ScalingError, OSError) as exc:
            raise HTTPException(409, str(exc)) from None

    @router.post("/runs/{run_id}/risk-scan/{scan_id}/resume")
    def resume_risk_scan(run_id: str, scan_id: str, actor: RunWriter):
        visible(run_id, actor)
        try:
            return set_scan_action(
                run_id, scan_id, actor.organization_id, actor.workspace_id, "resume"
            )
        except KeyError:
            raise HTTPException(404, "Risk scan not found.") from None
        except (ScalingError, OSError) as exc:
            raise HTTPException(409, str(exc)) from None

    return router

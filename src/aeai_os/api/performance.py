"""Read-only, workspace-scoped evidence verification and execution metrics."""

from __future__ import annotations

from statistics import mean
from typing import Any

from fastapi import APIRouter, HTTPException

from aeai_os.api.auth import RunReader
from aeai_os.schemas.enums import RunStatus


def _visible(run: Any, actor: Any) -> bool:
    return actor.can_access(
        run.metadata.get("organization_id", "local-org"),
        run.metadata.get("workspace_id", "default"),
    )


def _summary(repository: Any, run_id: str) -> dict[str, Any]:
    items = [
        event.payload["verification_summary"]
        for event in repository.list_events(run_id)
        if isinstance(event.payload, dict)
        and isinstance(event.payload.get("verification_summary"), dict)
    ]
    return (
        items[-1]
        if items
        else {
            "status": "not_checked",
            "reason": "Independent verification is generated for new managed workflow executions.",
        }
    )


def build_performance_router(repository: Any) -> APIRouter:
    router = APIRouter(prefix="/performance", tags=["performance"])

    @router.get("/summary")
    def summary(actor: RunReader) -> dict[str, Any]:
        visible = [run for run in repository.list_runs() if _visible(run, actor)]
        recent = sorted(visible, key=lambda run: run.created_at, reverse=True)[:100]
        audits = []
        durations = []
        totals = {
            "verified": 0,
            "mismatch": 0,
            "skipped": 0,
            "unavailable": 0,
            "not_checked": 0,
            "failed": 0,
        }
        scanned = 0
        for run in recent:
            check = _summary(repository, run.id)
            state = str(check.get("status", "not_checked"))
            totals[state] = totals.get(state, 0) + 1
            # Show records only when full source was audited, not partial cap checks.
            if state in {"verified", "mismatch"}:
                scanned += int(check.get("rows_scanned") or 0)
            for job in repository.list_workflow_jobs(run_id=run.id):
                if job.started_at and job.finished_at:
                    duration = (job.finished_at - job.started_at).total_seconds()
                    if 0 <= duration <= 31_536_000:
                        durations.append(duration)
            if run.status == RunStatus.COMPLETED and state != "not_checked":
                audits.append(
                    {
                        "run_id": run.id,
                        "task": run.task[:110],
                        "status": state,
                        "rows_scanned": check.get("rows_scanned"),
                        "checks_passed": check.get("checks_passed"),
                        "checks_total": check.get("checks_total"),
                    }
                )
        return {
            "runs_sampled": len(recent),
            "completed_runs": sum(run.status == RunStatus.COMPLETED for run in recent),
            "audited_rows": scanned,
            "verification": totals,
            "average_job_duration_seconds": round(mean(durations), 2) if durations else None,
            "measured_jobs": len(durations),
            "recent_verifications": audits[:6],
            "description": "Recorded source-to-KPI checks, not a statistical accuracy score or combined spending total.",  # noqa: E501
        }

    @router.get("/runs/{run_id}/verification")
    def verification(run_id: str, actor: RunReader) -> dict[str, Any]:
        try:
            run = repository.get_run(run_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="Run not found.") from None
        if not _visible(run, actor):
            raise HTTPException(status_code=404, detail="Run not found.")
        return {"run_id": run_id, **_summary(repository, run_id)}

    return router

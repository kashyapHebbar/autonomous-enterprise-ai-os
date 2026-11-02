"""Authenticated, read-only runtime status for the React Operations Center.

No arbitrary shell commands, environment changes, process spawning or secret
reads are exposed. Business actions already live in governed routers.
"""

from __future__ import annotations

from fastapi import APIRouter

from aeai_os.api.auth import RunReader
from aeai_os.operations.heartbeat import read_heartbeat
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.security.redaction import redact_value
from aeai_os.settings import AppSettings


def build_operations_router(repository, settings: AppSettings) -> APIRouter:
    router = APIRouter(prefix="/operations", tags=["operations"])

    @router.get("/status")
    def status(actor: RunReader) -> dict:
        # Filter every run before counting jobs or returning task text.
        visible = [
            run
            for run in repository.list_runs()
            if actor.can_access(
                run.metadata.get("organization_id", "local-org"),
                run.metadata.get("workspace_id", "default"),
            )
        ]
        latest = sorted(visible, key=lambda run: run.created_at, reverse=True)[:200]
        jobs = []
        for run in latest:
            for job in repository.list_workflow_jobs(run_id=run.id):
                jobs.append(
                    {
                        "id": job.id,
                        "run_id": run.id,
                        "task": run.task[:160],
                        "status": job.status.value,
                        "created_at": job.created_at.isoformat(),
                        "attempt_count": job.attempt_count,
                        "max_attempts": job.max_attempts,
                        "error_summary": redact_value(job.error_summary),
                    }
                )
        jobs.sort(key=lambda job: job["created_at"], reverse=True)
        tally = {
            name: sum(item["status"] == name for item in jobs)
            for name in ("queued", "running", "failed", "dead_letter", "completed")
        }
        embedded = type(repository) is InMemoryRunRepository
        worker = (
            {"online": True, "active": False, "last_seen": None} if embedded else read_heartbeat()
        )
        mode = "inline" if embedded else "managed"
        worker["mode"] = mode
        # The monitor store's heartbeat is already exposed at /monitoring/summary.
        # Do not read across tenants or mix monitor data into the run queue.
        if not embedded and tally["queued"] and not worker["online"]:
            guidance = "Workflow worker offline. Start the managed stack or check your deployment worker service."  # noqa: E501
        elif tally["queued"]:
            guidance = "Jobs are queued and should be claimed automatically."
        else:
            guidance = "No investigations waiting in this workspace."
        return {
            "workflow_worker": worker,
            "queue": tally,
            "guidance": guidance,
            "jobs": jobs[:50],
            "execution_mode": settings.workflow_execution_mode,
            "repository": "persistent" if not embedded else "temporary",
            "actions": {"retry_dead_letter": True, "arbitrary_shell": False},
        }

    return router

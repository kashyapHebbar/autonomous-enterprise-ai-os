from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aeai_os.runs.models import WorkflowJobRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import RunStatus, WorkflowJobStatus
from aeai_os.workflows.procurement import execute_procurement_workflow

PROCUREMENT_WORKFLOW_NAME = "procurement"


def enqueue_procurement_workflow(
    repository: InMemoryRunRepository,
    run_id: str,
    max_attempts: int = 3,
) -> WorkflowJobRecord:
    return repository.enqueue_workflow_job(
        run_id=run_id,
        workflow_name=PROCUREMENT_WORKFLOW_NAME,
        payload={"workflow": PROCUREMENT_WORKFLOW_NAME},
        max_attempts=max_attempts,
    )


class WorkflowWorker:
    """Processes queued workflow jobs with the same repository contract used by the API."""

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        worker_id: str | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_root = Path(artifact_root)
        self.worker_id = worker_id or f"worker_{uuid4().hex}"

    def process_next_job(self) -> WorkflowJobRecord | None:
        job = self._repository.claim_next_workflow_job(
            worker_id=self.worker_id,
            workflow_name=PROCUREMENT_WORKFLOW_NAME,
        )
        if job is None:
            return None
        return self._process_claimed_job(job)

    def _process_claimed_job(self, job: WorkflowJobRecord) -> WorkflowJobRecord:
        if job.workflow_name != PROCUREMENT_WORKFLOW_NAME:
            return self._final_fail(job, f"Unsupported workflow: {job.workflow_name}")

        try:
            result = execute_procurement_workflow(
                repository=self._repository,
                artifact_root=self._artifact_root,
                run_id=job.run_id,
            )
        except Exception as exc:
            return self._retry_or_fail(job, str(exc))

        if result.status == RunStatus.FAILED:
            message = (
                self._repository.get_run(job.run_id).error_summary
                or "Workflow execution failed."
            )
            return self._final_fail(job, message)
        return self._repository.complete_workflow_job(job.id)

    def _retry_or_fail(self, job: WorkflowJobRecord, error_summary: str) -> WorkflowJobRecord:
        updated = self._repository.fail_workflow_job(
            job_id=job.id,
            error_summary=error_summary,
            retry=True,
        )
        if updated.status == WorkflowJobStatus.FAILED:
            self._repository.update_status(
                job.run_id,
                RunStatus.FAILED,
                error_summary=error_summary,
            )
        return updated

    def _final_fail(self, job: WorkflowJobRecord, error_summary: str) -> WorkflowJobRecord:
        updated = self._repository.fail_workflow_job(
            job_id=job.id,
            error_summary=error_summary,
            retry=False,
        )
        self._repository.update_status(
            job.run_id,
            RunStatus.FAILED,
            error_summary=error_summary,
        )
        return updated

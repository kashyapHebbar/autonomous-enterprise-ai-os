from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aeai_os.observability.tracing import start_span, trace_context
from aeai_os.runs.models import WorkflowJobRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import RunStatus, WorkflowJobStatus
from aeai_os.storage import ArtifactStore
from aeai_os.workflows.procurement import execute_procurement_workflow
from aeai_os.workflows.queue import RepositoryWorkflowQueue, WorkflowQueueBackend

PROCUREMENT_WORKFLOW_NAME = "procurement"


def enqueue_procurement_workflow(
    repository: InMemoryRunRepository,
    run_id: str,
    max_attempts: int = 3,
    queue: WorkflowQueueBackend | None = None,
) -> WorkflowJobRecord:
    workflow_queue = queue or RepositoryWorkflowQueue(repository)
    run = repository.get_run(run_id)
    with trace_context(
        {
            "run.id": run_id,
            "run.trace_id": run.trace_id,
            "workflow.name": PROCUREMENT_WORKFLOW_NAME,
        }
    ):
        with start_span("workflow.enqueue"):
            return workflow_queue.enqueue(
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
        queue: WorkflowQueueBackend | None = None,
        claim_timeout_seconds: int | None = 300,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue or RepositoryWorkflowQueue(repository)
        self._artifact_root = Path(artifact_root)
        self._artifact_store = artifact_store
        self.worker_id = worker_id or f"worker_{uuid4().hex}"
        self._claim_timeout_seconds = claim_timeout_seconds

    def process_next_job(self) -> WorkflowJobRecord | None:
        job = self._queue.claim_next(
            worker_id=self.worker_id,
            workflow_name=PROCUREMENT_WORKFLOW_NAME,
            stale_after_seconds=self._claim_timeout_seconds,
        )
        if job is None:
            return None
        return self._process_claimed_job(job)

    def heartbeat_job(self, job_id: str) -> WorkflowJobRecord:
        return self._queue.heartbeat(job_id=job_id, worker_id=self.worker_id)

    def _process_claimed_job(self, job: WorkflowJobRecord) -> WorkflowJobRecord:
        run = self._repository.get_run(job.run_id)
        with trace_context(
            {
                "run.id": job.run_id,
                "run.trace_id": run.trace_id,
                "workflow.name": job.workflow_name,
                "workflow.job.id": job.id,
                "workflow.job.attempt": job.attempt_count,
                "worker.id": self.worker_id,
            }
        ):
            with start_span("workflow.worker.process_job") as span:
                self.heartbeat_job(job.id)
                if job.workflow_name != PROCUREMENT_WORKFLOW_NAME:
                    span.set_attribute("error", True)
                    return self._final_fail(
                        job,
                        f"Unsupported workflow: {job.workflow_name}",
                    )

                try:
                    result = execute_procurement_workflow(
                        repository=self._repository,
                        artifact_root=self._artifact_root,
                        run_id=job.run_id,
                        artifact_store=self._artifact_store,
                    )
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_attribute("error", True)
                    return self._retry_or_fail(job, str(exc))

                span.set_attribute("run.status", result.status.value)
                if result.status == RunStatus.FAILED:
                    span.set_attribute("error", True)
                    message = (
                        self._repository.get_run(job.run_id).error_summary
                        or "Workflow execution failed."
                    )
                    return self._final_fail(job, message)
                return self._queue.complete(job_id=job.id, worker_id=self.worker_id)

    def _retry_or_fail(self, job: WorkflowJobRecord, error_summary: str) -> WorkflowJobRecord:
        updated = self._queue.fail(
            job_id=job.id,
            worker_id=self.worker_id,
            error_summary=error_summary,
            retry=True,
        )
        if updated.status in {WorkflowJobStatus.FAILED, WorkflowJobStatus.DEAD_LETTER}:
            self._repository.update_status(
                job.run_id,
                RunStatus.FAILED,
                error_summary=error_summary,
            )
        return updated

    def _final_fail(self, job: WorkflowJobRecord, error_summary: str) -> WorkflowJobRecord:
        updated = self._queue.fail(
            job_id=job.id,
            worker_id=self.worker_id,
            error_summary=error_summary,
            retry=False,
        )
        self._repository.update_status(
            job.run_id,
            RunStatus.FAILED,
            error_summary=error_summary,
        )
        return updated

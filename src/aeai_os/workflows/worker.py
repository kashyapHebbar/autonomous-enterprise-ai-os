from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from aeai_os.connectors import ConnectorRegistry
from aeai_os.observability.tracing import start_span, trace_context
from aeai_os.runs.models import WorkflowJobRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import RunStatus, WorkflowJobStatus
from aeai_os.storage import ArtifactStore
from aeai_os.workflows.dynamic import execute_dynamic_workflow
from aeai_os.workflows.procurement import execute_procurement_workflow
from aeai_os.workflows.queue import RepositoryWorkflowQueue, WorkflowQueueBackend

PROCUREMENT_WORKFLOW_NAME = "procurement"
DYNAMIC_WORKFLOW_NAME = "dynamic_analysis"


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


def enqueue_dynamic_workflow(
    repository: InMemoryRunRepository,
    run_id: str,
    queue: WorkflowQueueBackend | None = None,
) -> WorkflowJobRecord:
    """Queue a fresh dynamic run; one attempt prevents replay of side-effecting nodes."""
    run = repository.get_run(run_id)
    if not run.dataset_artifact_id:
        raise ValueError("Attach a dataset before executing the workflow.")
    if run.status != RunStatus.PENDING:
        raise ValueError("Only a pending run may be submitted for asynchronous execution.")
    if any(
        job.status in {WorkflowJobStatus.QUEUED, WorkflowJobStatus.RUNNING}
        for job in repository.list_workflow_jobs(run_id=run_id)
    ):
        raise ValueError("This run already has an active workflow job.")
    workflow_queue = queue or RepositoryWorkflowQueue(repository)
    with trace_context(
        {"run.id": run_id, "run.trace_id": run.trace_id, "workflow.name": DYNAMIC_WORKFLOW_NAME}
    ):
        with start_span("workflow.enqueue"):
            job = workflow_queue.enqueue(
                run_id=run_id,
                workflow_name=DYNAMIC_WORKFLOW_NAME,
                payload={"workflow": DYNAMIC_WORKFLOW_NAME},
                max_attempts=1,
            )
            repository.update_status(run_id, RunStatus.QUEUED)
            return job


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
        connector_registry: ConnectorRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._queue = queue or RepositoryWorkflowQueue(repository)
        self._artifact_root = Path(artifact_root)
        self._artifact_store = artifact_store
        self._connector_registry = connector_registry
        self._next_workflow_index = 0
        self.worker_id = worker_id or f"worker_{uuid4().hex}"
        self._claim_timeout_seconds = claim_timeout_seconds

    def process_next_job(self) -> WorkflowJobRecord | None:
        # Claim by named queue so Redis-backed deployments pop their queue indexes.
        # Rotate precedence so continuous procurement work cannot starve dynamic jobs.
        workflow_names = (PROCUREMENT_WORKFLOW_NAME, DYNAMIC_WORKFLOW_NAME)
        first = self._next_workflow_index % len(workflow_names)
        self._next_workflow_index += 1
        for offset in range(len(workflow_names)):
            job = self._queue.claim_next(
                worker_id=self.worker_id,
                workflow_name=workflow_names[(first + offset) % len(workflow_names)],
                stale_after_seconds=self._claim_timeout_seconds,
            )
            if job is not None:
                return self._process_claimed_job(job)
        return None

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
                try:
                    if job.workflow_name == PROCUREMENT_WORKFLOW_NAME:
                        result = execute_procurement_workflow(
                            repository=self._repository,
                            artifact_root=self._artifact_root,
                            run_id=job.run_id,
                            artifact_store=self._artifact_store,
                            connector_registry=self._connector_registry,
                        )
                    elif job.workflow_name == DYNAMIC_WORKFLOW_NAME:
                        result = execute_dynamic_workflow(
                            repository=self._repository,
                            artifact_root=self._artifact_root,
                            run_id=job.run_id,
                            artifact_store=self._artifact_store,
                            connector_registry=self._connector_registry,
                        )
                    else:
                        return self._final_fail(job, f"Unsupported workflow: {job.workflow_name}")
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
                # Upgrade 13: independently reconcile recorded KPIs with a
                # bounded, streaming read of the source. Never rerun the model.
                # Audit failure must not rewrite a successfully completed run.
                if self._artifact_store is not None:
                    try:
                        from aeai_os.quality.reconcile import verify_run

                        verify_run(self._repository, self._artifact_store, job.run_id)
                    except Exception:
                        # Reporting is best effort; workflow result remains authoritative.
                        import logging

                        logging.getLogger(__name__).exception(
                            "Post-run evidence verification failed"
                        )
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

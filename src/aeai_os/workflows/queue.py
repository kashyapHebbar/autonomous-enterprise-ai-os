from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from aeai_os.runs.models import WorkflowJobRecord
from aeai_os.runs.repository import InMemoryRunRepository, WorkflowJobNotFoundError
from aeai_os.schemas.enums import WorkflowJobStatus
from aeai_os.settings import AppSettings


class WorkflowQueueBackend(Protocol):
    """Queue contract used by API enqueue paths and distributed workers."""

    def enqueue(
        self,
        *,
        run_id: str,
        workflow_name: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> WorkflowJobRecord:
        ...

    def claim_next(
        self,
        *,
        worker_id: str,
        workflow_name: str | None = None,
        stale_after_seconds: int | None = None,
    ) -> WorkflowJobRecord | None:
        ...

    def heartbeat(self, *, job_id: str, worker_id: str) -> WorkflowJobRecord:
        ...

    def complete(self, *, job_id: str, worker_id: str) -> WorkflowJobRecord:
        ...

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_summary: str,
        retry: bool = True,
    ) -> WorkflowJobRecord:
        ...

    def recover_timed_out(
        self,
        *,
        timeout_seconds: int,
        workflow_name: str | None = None,
    ) -> list[WorkflowJobRecord]:
        ...

    def retry_dead_letter(
        self,
        *,
        job_id: str,
        reason: str | None = None,
    ) -> WorkflowJobRecord:
        ...

    def dismiss_dead_letter(
        self,
        *,
        job_id: str,
        reason: str | None = None,
    ) -> WorkflowJobRecord:
        ...


@dataclass
class RepositoryWorkflowQueue:
    """Queue backend backed by the configured run repository.

    This is the default local and test backend. With the SQLAlchemy repository, it also gives
    Docker Compose and Kubernetes workers durable queue state through Postgres.
    """

    repository: InMemoryRunRepository

    def enqueue(
        self,
        *,
        run_id: str,
        workflow_name: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> WorkflowJobRecord:
        return self.repository.enqueue_workflow_job(
            run_id=run_id,
            workflow_name=workflow_name,
            payload=payload,
            max_attempts=max_attempts,
        )

    def claim_next(
        self,
        *,
        worker_id: str,
        workflow_name: str | None = None,
        stale_after_seconds: int | None = None,
    ) -> WorkflowJobRecord | None:
        return self.repository.claim_next_workflow_job(
            worker_id=worker_id,
            workflow_name=workflow_name,
            stale_after_seconds=stale_after_seconds,
        )

    def heartbeat(self, *, job_id: str, worker_id: str) -> WorkflowJobRecord:
        return self.repository.heartbeat_workflow_job(job_id=job_id, worker_id=worker_id)

    def complete(self, *, job_id: str, worker_id: str) -> WorkflowJobRecord:
        return self.repository.complete_workflow_job(job_id=job_id, worker_id=worker_id)

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_summary: str,
        retry: bool = True,
    ) -> WorkflowJobRecord:
        return self.repository.fail_workflow_job(
            job_id=job_id,
            error_summary=error_summary,
            retry=retry,
            worker_id=worker_id,
        )

    def recover_timed_out(
        self,
        *,
        timeout_seconds: int,
        workflow_name: str | None = None,
    ) -> list[WorkflowJobRecord]:
        return self.repository.recover_timed_out_workflow_jobs(
            timeout_seconds=timeout_seconds,
            workflow_name=workflow_name,
        )

    def retry_dead_letter(
        self,
        *,
        job_id: str,
        reason: str | None = None,
    ) -> WorkflowJobRecord:
        return self.repository.retry_dead_letter_workflow_job(
            job_id=job_id,
            reason=reason,
        )

    def dismiss_dead_letter(
        self,
        *,
        job_id: str,
        reason: str | None = None,
    ) -> WorkflowJobRecord:
        return self.repository.dismiss_dead_letter_workflow_job(
            job_id=job_id,
            reason=reason,
        )


class RedisWorkflowQueue(RepositoryWorkflowQueue):
    """Redis-backed queue index with repository-backed job state.

    Redis stores pending job ids for fast distributed worker fan-out. The repository remains the
    authoritative execution guard, so duplicate Redis entries or stale ids cannot double-execute.
    """

    def __init__(
        self,
        repository: InMemoryRunRepository,
        *,
        redis_url: str,
        key_prefix: str = "aeai:workflow",
        redis_client: Any | None = None,
        max_pop_attempts: int = 100,
    ) -> None:
        super().__init__(repository=repository)
        self._key_prefix = key_prefix.strip(":") or "aeai:workflow"
        self._max_pop_attempts = max_pop_attempts
        if redis_client is not None:
            self._redis = redis_client
        else:
            from redis import Redis

            self._redis = Redis.from_url(redis_url, decode_responses=True)

    def enqueue(
        self,
        *,
        run_id: str,
        workflow_name: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> WorkflowJobRecord:
        job = super().enqueue(
            run_id=run_id,
            workflow_name=workflow_name,
            payload=payload,
            max_attempts=max_attempts,
        )
        self._push_job(job)
        return job

    def claim_next(
        self,
        *,
        worker_id: str,
        workflow_name: str | None = None,
        stale_after_seconds: int | None = None,
    ) -> WorkflowJobRecord | None:
        if stale_after_seconds is not None:
            self.recover_timed_out(
                timeout_seconds=stale_after_seconds,
                workflow_name=workflow_name,
            )

        if workflow_name:
            for _ in range(self._max_pop_attempts):
                job_id = self._redis.lpop(self._queue_key(workflow_name))
                if job_id is None:
                    break
                try:
                    job = self.repository.claim_workflow_job(job_id, worker_id=worker_id)
                except WorkflowJobNotFoundError:
                    continue
                if job is not None:
                    return job

        return super().claim_next(
            worker_id=worker_id,
            workflow_name=workflow_name,
            stale_after_seconds=None,
        )

    def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_summary: str,
        retry: bool = True,
    ) -> WorkflowJobRecord:
        job = super().fail(
            job_id=job_id,
            worker_id=worker_id,
            error_summary=error_summary,
            retry=retry,
        )
        if job.status == WorkflowJobStatus.QUEUED:
            self._push_job(job)
        return job

    def recover_timed_out(
        self,
        *,
        timeout_seconds: int,
        workflow_name: str | None = None,
    ) -> list[WorkflowJobRecord]:
        recovered = super().recover_timed_out(
            timeout_seconds=timeout_seconds,
            workflow_name=workflow_name,
        )
        for job in recovered:
            if job.status == WorkflowJobStatus.QUEUED:
                self._push_job(job)
        return recovered

    def retry_dead_letter(
        self,
        *,
        job_id: str,
        reason: str | None = None,
    ) -> WorkflowJobRecord:
        job = super().retry_dead_letter(job_id=job_id, reason=reason)
        self._push_job(job)
        return job

    def _push_job(self, job: WorkflowJobRecord) -> None:
        self._redis.rpush(self._queue_key(job.workflow_name), job.id)

    def _queue_key(self, workflow_name: str) -> str:
        return f"{self._key_prefix}:queue:{workflow_name}"


def build_workflow_queue(
    settings: AppSettings,
    repository: InMemoryRunRepository,
) -> WorkflowQueueBackend:
    backend = settings.workflow_queue_backend.strip().lower()
    if backend in {"repository", "local", "memory"}:
        return RepositoryWorkflowQueue(repository=repository)
    if backend == "redis":
        return RedisWorkflowQueue(
            repository=repository,
            redis_url=settings.redis_url,
            key_prefix=settings.workflow_queue_key_prefix,
        )
    if backend == "kafka":
        raise ValueError("Kafka workflow queue backend is not implemented yet; use redis.")
    raise ValueError(f"Unsupported workflow queue backend: {settings.workflow_queue_backend}")

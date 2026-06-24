from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from aeai_os.observability.tracing import ensure_trace_id, start_span
from aeai_os.runs.models import (
    AgentEventRecord,
    ArtifactRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
    RunCheckpointRecord,
    RunRecord,
    WorkflowJobRecord,
)
from aeai_os.schemas.enums import AgentEventType, ArtifactType, RunStatus, WorkflowJobStatus


class RunNotFoundError(KeyError):
    pass


class GraphNodeNotFoundError(KeyError):
    pass


class ArtifactNotFoundError(KeyError):
    pass


class RunCheckpointNotFoundError(KeyError):
    pass


class EvaluationResultNotFoundError(KeyError):
    pass


class WorkflowJobNotFoundError(KeyError):
    pass


class InMemoryRunRepository:
    """In-memory run repository for local development and fast tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._runs: dict[str, RunRecord] = {}
        self._artifacts: dict[str, list[ArtifactRecord]] = {}
        self._graph_nodes: dict[str, list[GraphNodeRecord]] = {}
        self._events: dict[str, list[AgentEventRecord]] = {}
        self._evaluations: dict[str, list[EvaluationResultRecord]] = {}
        self._checkpoints: dict[str, RunCheckpointRecord] = {}
        self._workflow_jobs: dict[str, WorkflowJobRecord] = {}
        self._workflow_job_order: list[str] = []

    def create_run(
        self,
        task: str,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> RunRecord:
        normalized_task = task.strip()
        if len(normalized_task) < 3:
            raise ValueError("Task must contain at least 3 non-whitespace characters.")

        now = utc_now()
        run = RunRecord(
            id=f"run_{uuid4().hex}",
            task=normalized_task,
            status=RunStatus.PENDING,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
            trace_id=ensure_trace_id(trace_id),
        )
        with self._lock:
            self._runs[run.id] = run
            self._artifacts[run.id] = []
            self._graph_nodes[run.id] = []
            self._events[run.id] = []
            self._evaluations[run.id] = []
        return run

    def list_runs(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda run: run.created_at)

    def get_run(self, run_id: str) -> RunRecord:
        with self._lock:
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise RunNotFoundError(f"Run not found: {run_id}") from exc

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_summary: str | None = None,
    ) -> RunRecord:
        with self._lock:
            run = self.get_run(run_id)
            updated = replace(
                run,
                status=status,
                error_summary=error_summary,
                updated_at=utc_now(),
            )
            self._runs[run_id] = updated
            return updated

    def enqueue_workflow_job(
        self,
        run_id: str,
        workflow_name: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        job_id: str | None = None,
    ) -> WorkflowJobRecord:
        normalized_workflow = workflow_name.strip()
        if not normalized_workflow:
            raise ValueError("Workflow name is required.")
        if max_attempts < 1:
            raise ValueError("Workflow job max_attempts must be at least 1.")

        with self._lock:
            self.get_run(run_id)
            now = utc_now()
            job = WorkflowJobRecord(
                id=job_id or f"job_{uuid4().hex}",
                run_id=run_id,
                workflow_name=normalized_workflow,
                status=WorkflowJobStatus.QUEUED,
                payload=deepcopy(payload or {}),
                attempt_count=0,
                max_attempts=max_attempts,
                created_at=now,
                updated_at=now,
            )
            self._workflow_jobs[job.id] = job
            self._workflow_job_order.append(job.id)
            return job

    def list_workflow_jobs(
        self,
        run_id: str | None = None,
        status: WorkflowJobStatus | None = None,
    ) -> list[WorkflowJobRecord]:
        with self._lock:
            if run_id is not None:
                self.get_run(run_id)
            jobs = [self._workflow_jobs[job_id] for job_id in self._workflow_job_order]
            if run_id is not None:
                jobs = [job for job in jobs if job.run_id == run_id]
            if status is not None:
                jobs = [job for job in jobs if job.status == status]
            return [deepcopy(job) for job in jobs]

    def get_workflow_job(self, job_id: str) -> WorkflowJobRecord:
        with self._lock:
            try:
                return deepcopy(self._workflow_jobs[job_id])
            except KeyError as exc:
                raise WorkflowJobNotFoundError(f"Workflow job not found: {job_id}") from exc

    def claim_next_workflow_job(
        self,
        worker_id: str,
        workflow_name: str | None = None,
    ) -> WorkflowJobRecord | None:
        normalized_workflow = workflow_name.strip() if workflow_name else None
        with self._lock:
            for job_id in self._workflow_job_order:
                job = self._workflow_jobs[job_id]
                if job.status != WorkflowJobStatus.QUEUED:
                    continue
                if normalized_workflow is not None and job.workflow_name != normalized_workflow:
                    continue
                now = utc_now()
                claimed = replace(
                    job,
                    status=WorkflowJobStatus.RUNNING,
                    worker_id=worker_id,
                    attempt_count=job.attempt_count + 1,
                    started_at=job.started_at or now,
                    updated_at=now,
                )
                self._workflow_jobs[job_id] = claimed
                return deepcopy(claimed)
        return None

    def complete_workflow_job(self, job_id: str) -> WorkflowJobRecord:
        with self._lock:
            job = self._get_workflow_job_for_update(job_id)
            now = utc_now()
            completed = replace(
                job,
                status=WorkflowJobStatus.COMPLETED,
                updated_at=now,
                finished_at=now,
            )
            self._workflow_jobs[job_id] = completed
            return deepcopy(completed)

    def fail_workflow_job(
        self,
        job_id: str,
        error_summary: str,
        retry: bool = True,
    ) -> WorkflowJobRecord:
        with self._lock:
            job = self._get_workflow_job_for_update(job_id)
            now = utc_now()
            should_retry = retry and job.attempt_count < job.max_attempts
            failed = replace(
                job,
                status=(
                    WorkflowJobStatus.QUEUED
                    if should_retry
                    else WorkflowJobStatus.FAILED
                ),
                worker_id=None if should_retry else job.worker_id,
                error_summary=error_summary,
                updated_at=now,
                finished_at=None if should_retry else now,
            )
            self._workflow_jobs[job_id] = failed
            return deepcopy(failed)

    def next_artifact_id(self) -> str:
        return f"artifact_{uuid4().hex}"

    def add_artifact(
        self,
        run_id: str,
        artifact_type: ArtifactType,
        uri: str,
        metadata: dict[str, Any] | None = None,
        source_artifact_ids: list[str] | None = None,
        producer_node_id: str | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        with self._lock:
            run = self.get_run(run_id)
            artifact = ArtifactRecord(
                id=artifact_id or self.next_artifact_id(),
                run_id=run_id,
                producer_node_id=producer_node_id,
                type=artifact_type,
                uri=uri,
                metadata=dict(metadata or {}),
                source_artifact_ids=list(source_artifact_ids or []),
                created_at=utc_now(),
            )
            self._artifacts[run_id].append(artifact)
            if artifact.type == ArtifactType.DATASET:
                self._runs[run_id] = replace(
                    run,
                    dataset_artifact_id=artifact.id,
                    updated_at=utc_now(),
                )
            return artifact

    def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        with self._lock:
            self.get_run(run_id)
            return list(self._artifacts[run_id])

    def get_artifact(self, run_id: str, artifact_id: str) -> ArtifactRecord:
        with self._lock:
            self.get_run(run_id)
            for artifact in self._artifacts[run_id]:
                if artifact.id == artifact_id:
                    return artifact
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")

    def add_graph_node(self, node: GraphNodeRecord) -> GraphNodeRecord:
        return self.upsert_graph_node(node)

    def upsert_graph_node(self, node: GraphNodeRecord) -> GraphNodeRecord:
        with self._lock:
            self.get_run(node.run_id)
            nodes = self._graph_nodes[node.run_id]
            for index, existing in enumerate(nodes):
                if existing.id == node.id:
                    nodes[index] = node
                    break
            else:
                nodes.append(node)
            return node

    def get_graph_node(self, run_id: str, node_id: str) -> GraphNodeRecord:
        with self._lock:
            self.get_run(run_id)
            for node in self._graph_nodes[run_id]:
                if node.id == node_id:
                    return node
            raise GraphNodeNotFoundError(f"Graph node not found: {node_id}")

    def list_graph_nodes(self, run_id: str) -> list[GraphNodeRecord]:
        with self._lock:
            self.get_run(run_id)
            return list(self._graph_nodes[run_id])

    def add_event(self, event: AgentEventRecord) -> AgentEventRecord:
        with self._lock:
            self.get_run(event.run_id)
            self._events[event.run_id].append(event)
            return event

    def list_events(self, run_id: str) -> list[AgentEventRecord]:
        with self._lock:
            self.get_run(run_id)
            return list(self._events[run_id])

    def add_evaluation(self, evaluation: EvaluationResultRecord) -> EvaluationResultRecord:
        with self._lock:
            run = self.get_run(evaluation.run_id)
            record = evaluation
            if record.created_at is None:
                record = replace(record, created_at=utc_now())
            with start_span(
                "evaluation.result",
                {
                    "run.id": record.run_id,
                    "run.trace_id": run.trace_id,
                    "evaluation.id": record.id,
                    "evaluation.score": record.score,
                    "evaluation.passed": record.passed,
                    "evaluation.check_count": len(record.checks),
                    "evaluation.target_artifact_id": record.target_artifact_id,
                },
            ):
                self._evaluations[evaluation.run_id].append(record)
                self._events[evaluation.run_id].append(
                    AgentEventRecord(
                        id=f"event_{uuid4().hex}",
                        run_id=record.run_id,
                        node_id="evaluation",
                        event_type=AgentEventType.EVALUATION,
                        payload={
                            "message": "Evaluation result logged.",
                            "backend": "opentelemetry",
                            "evaluation_id": record.id,
                            "target_artifact_id": record.target_artifact_id,
                            "score": record.score,
                            "passed": record.passed,
                            "check_count": len(record.checks),
                            "trace_id": run.trace_id,
                            "timestamp": utc_now().isoformat(),
                        },
                        created_at=utc_now(),
                    )
                )
            return record

    def list_evaluations(self, run_id: str) -> list[EvaluationResultRecord]:
        with self._lock:
            self.get_run(run_id)
            return list(self._evaluations[run_id])

    def get_evaluation(self, run_id: str, evaluation_id: str) -> EvaluationResultRecord:
        with self._lock:
            self.get_run(run_id)
            for evaluation in self._evaluations[run_id]:
                if evaluation.id == evaluation_id:
                    return evaluation
            raise EvaluationResultNotFoundError(f"Evaluation result not found: {evaluation_id}")

    def save_checkpoint(self, run_id: str, state: dict[str, Any]) -> RunCheckpointRecord:
        with self._lock:
            self.get_run(run_id)
            now = utc_now()
            existing = self._checkpoints.get(run_id)
            checkpoint = RunCheckpointRecord(
                run_id=run_id,
                state=deepcopy(state),
                version=(existing.version + 1 if existing else 1),
                created_at=(existing.created_at if existing else now),
                updated_at=now,
            )
            self._checkpoints[run_id] = checkpoint
            return deepcopy(checkpoint)

    def get_checkpoint(self, run_id: str) -> RunCheckpointRecord:
        with self._lock:
            self.get_run(run_id)
            try:
                return deepcopy(self._checkpoints[run_id])
            except KeyError as exc:
                raise RunCheckpointNotFoundError(f"Run checkpoint not found: {run_id}") from exc

    def _get_workflow_job_for_update(self, job_id: str) -> WorkflowJobRecord:
        try:
            return self._workflow_jobs[job_id]
        except KeyError as exc:
            raise WorkflowJobNotFoundError(f"Workflow job not found: {job_id}") from exc


def utc_now() -> datetime:
    return datetime.now(UTC)

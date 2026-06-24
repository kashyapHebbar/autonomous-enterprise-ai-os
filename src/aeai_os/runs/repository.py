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
)
from aeai_os.schemas.enums import AgentEventType, ArtifactType, RunStatus


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


class InMemoryRunRepository:
    """Small repository used until the Postgres-backed implementation lands."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._runs: dict[str, RunRecord] = {}
        self._artifacts: dict[str, list[ArtifactRecord]] = {}
        self._graph_nodes: dict[str, list[GraphNodeRecord]] = {}
        self._events: dict[str, list[AgentEventRecord]] = {}
        self._evaluations: dict[str, list[EvaluationResultRecord]] = {}
        self._checkpoints: dict[str, RunCheckpointRecord] = {}

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


def utc_now() -> datetime:
    return datetime.now(UTC)

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from aeai_os.runs.models import (
    AgentEventRecord,
    ArtifactRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
    RunRecord,
)
from aeai_os.schemas.enums import ArtifactType, RunStatus


class RunNotFoundError(KeyError):
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

    def create_run(self, task: str, metadata: dict[str, Any] | None = None) -> RunRecord:
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

    def add_graph_node(self, node: GraphNodeRecord) -> GraphNodeRecord:
        with self._lock:
            self.get_run(node.run_id)
            self._graph_nodes[node.run_id].append(node)
            return node

    def add_event(self, event: AgentEventRecord) -> AgentEventRecord:
        with self._lock:
            self.get_run(event.run_id)
            self._events[event.run_id].append(event)
            return event

    def add_evaluation(self, evaluation: EvaluationResultRecord) -> EvaluationResultRecord:
        with self._lock:
            self.get_run(evaluation.run_id)
            record = evaluation
            if record.created_at is None:
                record = replace(record, created_at=utc_now())
            self._evaluations[evaluation.run_id].append(record)
            return record


def utc_now() -> datetime:
    return datetime.now(UTC)

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from aeai_os.runs.models import (
    AgentEventRecord,
    ArtifactRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
    RunCheckpointRecord,
    RunRecord,
    WorkflowJobRecord,
)
from aeai_os.runs.repository import RunCheckpointNotFoundError, RunNotFoundError, utc_now
from aeai_os.schemas.enums import ArtifactType, GraphNodeStatus, RunStatus, WorkflowJobStatus
from aeai_os.security.redaction import REDACTED as _REDACTED
from aeai_os.security.redaction import redact_text, redact_uri, redact_value

RUN_ARCHIVE_SCHEMA_VERSION = "aeai.run_archive.v1"
REDACTED = _REDACTED


class RunArchiveError(ValueError):
    pass


class RunArchiveConflictError(RunArchiveError):
    pass


def export_run_archive(repository: Any, run_id: str) -> dict[str, Any]:
    run = repository.get_run(run_id)
    try:
        checkpoint = repository.get_checkpoint(run_id)
    except RunCheckpointNotFoundError:
        checkpoint = None

    return {
        "schema_version": RUN_ARCHIVE_SCHEMA_VERSION,
        "exported_at": utc_now().isoformat(),
        "run": _run_to_archive(run),
        "artifacts": [
            _artifact_to_archive(artifact)
            for artifact in repository.list_artifacts(run_id)
        ],
        "graph_nodes": [
            _graph_node_to_archive(node)
            for node in repository.list_graph_nodes(run_id)
        ],
        "events": [
            _event_to_archive(event)
            for event in repository.list_events(run_id)
        ],
        "evaluations": [
            _evaluation_to_archive(evaluation)
            for evaluation in repository.list_evaluations(run_id)
        ],
        "workflow_jobs": [
            _workflow_job_to_archive(job)
            for job in repository.list_workflow_jobs(run_id=run_id)
        ],
        "checkpoint": _checkpoint_to_archive(checkpoint) if checkpoint else None,
        "notes": {
            "payloads_included": False,
            "usage": "Import this archive into a local repository for offline run inspection.",
        },
    }


def import_run_archive(
    repository: Any,
    archive: dict[str, Any],
    *,
    overwrite: bool = False,
) -> RunRecord:
    if archive.get("schema_version") != RUN_ARCHIVE_SCHEMA_VERSION:
        raise RunArchiveError(
            f"Unsupported run archive schema version: {archive.get('schema_version')}"
        )
    run = _run_from_archive(_required_mapping(archive, "run"))
    try:
        repository.get_run(run.id)
    except RunNotFoundError:
        pass
    else:
        if not overwrite:
            raise RunArchiveConflictError(f"Run already exists: {run.id}")

    restored = repository.restore_run(
        run,
        artifacts=[
            _artifact_from_archive(item)
            for item in archive.get("artifacts", [])
        ],
        graph_nodes=[
            _graph_node_from_archive(item)
            for item in archive.get("graph_nodes", [])
        ],
        events=[
            _event_from_archive(item)
            for item in archive.get("events", [])
        ],
        evaluations=[
            _evaluation_from_archive(item)
            for item in archive.get("evaluations", [])
        ],
        workflow_jobs=[
            _workflow_job_from_archive(item)
            for item in archive.get("workflow_jobs", [])
        ],
        checkpoint=(
            _checkpoint_from_archive(archive["checkpoint"])
            if archive.get("checkpoint")
            else None
        ),
    )
    return restored


def _run_to_archive(run: RunRecord) -> dict[str, Any]:
    return {
        "id": run.id,
        "task": redact_text(run.task) or "",
        "status": run.status.value,
        "metadata": redact_value(run.metadata),
        "dataset_artifact_id": run.dataset_artifact_id,
        "trace_id": run.trace_id,
        "error_summary": run.error_summary,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


def _artifact_to_archive(artifact: ArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "run_id": artifact.run_id,
        "producer_node_id": artifact.producer_node_id,
        "type": artifact.type.value,
        "uri": redact_uri(artifact.uri),
        "metadata": redact_value(artifact.metadata),
        "content_type": artifact.content_type,
        "storage_backend": artifact.storage_backend,
        "storage_key": redact_uri(artifact.storage_key) if artifact.storage_key else None,
        "size_bytes": artifact.size_bytes,
        "source_artifact_ids": list(artifact.source_artifact_ids),
        "created_at": artifact.created_at.isoformat(),
    }


def _graph_node_to_archive(node: GraphNodeRecord) -> dict[str, Any]:
    return {
        "id": node.id,
        "run_id": node.run_id,
        "agent_type": node.agent_type,
        "status": node.status.value,
        "depends_on": list(node.depends_on),
        "required_tools": list(node.required_tools),
        "expected_artifacts": list(node.expected_artifacts),
        "retry_count": node.retry_count,
        "started_at": node.started_at.isoformat() if node.started_at else None,
        "finished_at": node.finished_at.isoformat() if node.finished_at else None,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


def _event_to_archive(event: AgentEventRecord) -> dict[str, Any]:
    return {
        "id": event.id,
        "run_id": event.run_id,
        "node_id": event.node_id,
        "event_type": str(event.event_type),
        "payload": redact_value(event.payload),
        "created_at": event.created_at.isoformat(),
    }


def _evaluation_to_archive(evaluation: EvaluationResultRecord) -> dict[str, Any]:
    if evaluation.created_at is None:
        raise RunArchiveError(f"Evaluation is missing created_at: {evaluation.id}")
    return {
        "id": evaluation.id,
        "run_id": evaluation.run_id,
        "target_artifact_id": evaluation.target_artifact_id,
        "score": evaluation.score,
        "passed": evaluation.passed,
        "checks": redact_value(evaluation.checks),
        "created_at": evaluation.created_at.isoformat(),
    }


def _workflow_job_to_archive(job: WorkflowJobRecord) -> dict[str, Any]:
    return {
        "id": job.id,
        "run_id": job.run_id,
        "workflow_name": job.workflow_name,
        "status": job.status.value,
        "payload": redact_value(job.payload),
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "worker_id": job.worker_id,
        "error_summary": job.error_summary,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _checkpoint_to_archive(checkpoint: RunCheckpointRecord) -> dict[str, Any]:
    return {
        "run_id": checkpoint.run_id,
        "version": checkpoint.version,
        "state": redact_value(checkpoint.state),
        "created_at": checkpoint.created_at.isoformat(),
        "updated_at": checkpoint.updated_at.isoformat(),
    }


def _run_from_archive(payload: dict[str, Any]) -> RunRecord:
    return RunRecord(
        id=str(payload["id"]),
        task=str(payload["task"]),
        status=RunStatus(str(payload["status"])),
        metadata=deepcopy(payload.get("metadata") or {}),
        dataset_artifact_id=payload.get("dataset_artifact_id"),
        trace_id=payload.get("trace_id"),
        error_summary=payload.get("error_summary"),
        created_at=_parse_datetime(payload["created_at"]),
        updated_at=_parse_datetime(payload["updated_at"]),
    )


def _artifact_from_archive(payload: dict[str, Any]) -> ArtifactRecord:
    return ArtifactRecord(
        id=str(payload["id"]),
        run_id=str(payload["run_id"]),
        producer_node_id=payload.get("producer_node_id"),
        type=ArtifactType(str(payload["type"])),
        uri=str(payload["uri"]),
        metadata=deepcopy(payload.get("metadata") or {}),
        content_type=payload.get("content_type"),
        storage_backend=payload.get("storage_backend"),
        storage_key=payload.get("storage_key"),
        size_bytes=payload.get("size_bytes"),
        source_artifact_ids=list(payload.get("source_artifact_ids") or []),
        created_at=_parse_datetime(payload["created_at"]),
    )


def _graph_node_from_archive(payload: dict[str, Any]) -> GraphNodeRecord:
    return GraphNodeRecord(
        id=str(payload["id"]),
        run_id=str(payload["run_id"]),
        agent_type=str(payload["agent_type"]),
        status=GraphNodeStatus(str(payload["status"])),
        depends_on=list(payload.get("depends_on") or []),
        required_tools=list(payload.get("required_tools") or []),
        expected_artifacts=list(payload.get("expected_artifacts") or []),
        retry_count=int(payload.get("retry_count") or 0),
        started_at=_parse_optional_datetime(payload.get("started_at")),
        finished_at=_parse_optional_datetime(payload.get("finished_at")),
        created_at=_parse_datetime(payload["created_at"]),
        updated_at=_parse_datetime(payload["updated_at"]),
    )


def _event_from_archive(payload: dict[str, Any]) -> AgentEventRecord:
    return AgentEventRecord(
        id=str(payload["id"]),
        run_id=str(payload["run_id"]),
        node_id=str(payload["node_id"]),
        event_type=str(payload["event_type"]),
        payload=deepcopy(payload.get("payload") or {}),
        created_at=_parse_datetime(payload["created_at"]),
    )


def _evaluation_from_archive(payload: dict[str, Any]) -> EvaluationResultRecord:
    return EvaluationResultRecord(
        id=str(payload["id"]),
        run_id=str(payload["run_id"]),
        target_artifact_id=payload.get("target_artifact_id"),
        score=float(payload["score"]),
        passed=bool(payload["passed"]),
        checks=deepcopy(payload.get("checks") or []),
        created_at=_parse_datetime(payload["created_at"]),
    )


def _workflow_job_from_archive(payload: dict[str, Any]) -> WorkflowJobRecord:
    return WorkflowJobRecord(
        id=str(payload["id"]),
        run_id=str(payload["run_id"]),
        workflow_name=str(payload["workflow_name"]),
        status=WorkflowJobStatus(str(payload["status"])),
        payload=deepcopy(payload.get("payload") or {}),
        attempt_count=int(payload.get("attempt_count") or 0),
        max_attempts=int(payload.get("max_attempts") or 1),
        worker_id=payload.get("worker_id"),
        error_summary=payload.get("error_summary"),
        started_at=_parse_optional_datetime(payload.get("started_at")),
        finished_at=_parse_optional_datetime(payload.get("finished_at")),
        heartbeat_at=_parse_optional_datetime(payload.get("heartbeat_at")),
        created_at=_parse_datetime(payload["created_at"]),
        updated_at=_parse_datetime(payload["updated_at"]),
    )


def _checkpoint_from_archive(payload: dict[str, Any]) -> RunCheckpointRecord:
    return RunCheckpointRecord(
        run_id=str(payload["run_id"]),
        state=deepcopy(payload.get("state") or {}),
        version=int(payload.get("version") or 1),
        created_at=_parse_datetime(payload["created_at"]),
        updated_at=_parse_datetime(payload["updated_at"]),
    )


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RunArchiveError(f"Run archive is missing object: {key}")
    return value


def _parse_datetime(value: Any) -> datetime:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RunArchiveError(f"Invalid datetime in archive: {value}") from exc


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    return _parse_datetime(value)

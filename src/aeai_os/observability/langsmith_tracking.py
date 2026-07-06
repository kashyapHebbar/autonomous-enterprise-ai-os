from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid5

if TYPE_CHECKING:
    from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord, RunRecord


@dataclass(frozen=True)
class LangSmithTrackingConfig:
    enabled: bool = False
    api_key: str | None = None
    endpoint: str | None = None
    project_name: str = "Autonomous Enterprise AI OS"
    run_name_prefix: str = "aeai-run"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LangSmithLogResult:
    status: str
    message: str | None = None


class LangSmithTracker:
    def __init__(
        self,
        *,
        config: LangSmithTrackingConfig,
        client: Any | None = None,
        status: str,
        message: str | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.status = status
        self.message = message

    def log_agent_event(
        self,
        *,
        run: RunRecord,
        event: AgentEventRecord,
    ) -> LangSmithLogResult:
        if self.status != "configured" or self._client is None:
            return LangSmithLogResult(status=self.status, message=self.message)

        try:
            langsmith_run_id = _stable_langsmith_id("event", run.id, event.id)
            metadata = _agent_event_metadata(self.config, run, event)
            self._client.create_run(
                id=langsmith_run_id,
                name=_run_name(self.config, run.id, event.node_id, str(event.event_type)),
                run_type="chain",
                project_name=self.config.project_name,
                inputs={
                    "task": run.task,
                    "event_type": str(event.event_type),
                    "node_id": event.node_id,
                },
                metadata=metadata,
                tags=_tags(self.config, "agent-event", str(event.event_type)),
                start_time=event.created_at,
            )
            _finish_langsmith_run(
                self._client,
                langsmith_run_id,
                outputs={"payload": event.payload},
                end_time=event.created_at,
            )
        except Exception as exc:  # pragma: no cover - exercised with fake clients in tests
            return LangSmithLogResult(status="failed", message=str(exc))

        return LangSmithLogResult(status="logged")

    def log_evaluation(
        self,
        *,
        run: RunRecord,
        evaluation: EvaluationResultRecord,
    ) -> LangSmithLogResult:
        if self.status != "configured" or self._client is None:
            return LangSmithLogResult(status=self.status, message=self.message)

        try:
            langsmith_run_id = _stable_langsmith_id("evaluation", run.id, evaluation.id)
            metadata = _evaluation_metadata(self.config, run, evaluation)
            self._client.create_run(
                id=langsmith_run_id,
                name=_run_name(self.config, run.id, "evaluation", evaluation.id),
                run_type="chain",
                project_name=self.config.project_name,
                inputs={"task": run.task, "evaluation_id": evaluation.id},
                metadata=metadata,
                tags=_tags(self.config, "evaluation"),
                start_time=evaluation.created_at,
            )
            _finish_langsmith_run(
                self._client,
                langsmith_run_id,
                outputs={
                    "score": evaluation.score,
                    "passed": evaluation.passed,
                    "checks": evaluation.checks,
                },
                end_time=evaluation.created_at,
            )
        except Exception as exc:  # pragma: no cover - exercised with fake clients in tests
            return LangSmithLogResult(status="failed", message=str(exc))

        return LangSmithLogResult(status="logged")


def build_langsmith_tracking_config(
    env: Mapping[str, str] | None = None,
) -> LangSmithTrackingConfig:
    values = os.environ if env is None else env
    return LangSmithTrackingConfig(
        enabled=_parse_bool(
            values.get("AEAI_LANGSMITH_TRACING_ENABLED")
            or values.get("LANGSMITH_TRACING")
            or values.get("LANGCHAIN_TRACING_V2"),
            default=False,
        ),
        api_key=(
            values.get("AEAI_LANGSMITH_API_KEY")
            or values.get("LANGSMITH_API_KEY")
            or values.get("LANGCHAIN_API_KEY")
            or None
        ),
        endpoint=(
            values.get("AEAI_LANGSMITH_ENDPOINT")
            or values.get("LANGSMITH_ENDPOINT")
            or values.get("LANGCHAIN_ENDPOINT")
            or None
        ),
        project_name=(
            values.get("AEAI_LANGSMITH_PROJECT")
            or values.get("LANGSMITH_PROJECT")
            or values.get("LANGCHAIN_PROJECT")
            or "Autonomous Enterprise AI OS"
        ),
        run_name_prefix=values.get("AEAI_LANGSMITH_RUN_NAME_PREFIX") or "aeai-run",
        tags=_parse_tags(values.get("AEAI_LANGSMITH_TAGS") or ""),
    )


def build_langsmith_tracker(
    config: LangSmithTrackingConfig | None = None,
    *,
    client: Any | None = None,
    importer: Callable[[str], Any] = importlib.import_module,
) -> LangSmithTracker:
    resolved_config = config or build_langsmith_tracking_config()
    if not resolved_config.enabled:
        return LangSmithTracker(config=resolved_config, status="disabled")

    if not resolved_config.api_key:
        return LangSmithTracker(
            config=resolved_config,
            status="not_configured",
            message="LangSmith tracing requested but AEAI_LANGSMITH_API_KEY is not set.",
        )

    resolved_client = client
    if resolved_client is None:
        try:
            module = importer("langsmith")
        except ImportError:
            return LangSmithTracker(
                config=resolved_config,
                status="unavailable",
                message=(
                    "LangSmith tracing requested but the optional langsmith package is not "
                    "installed."
                ),
            )

        client_factory = getattr(module, "Client", None)
        if client_factory is None:
            return LangSmithTracker(
                config=resolved_config,
                status="unavailable",
                message="LangSmith tracing requested but langsmith.Client is unavailable.",
            )
        resolved_client = client_factory(**_client_kwargs(resolved_config))

    return LangSmithTracker(
        config=resolved_config,
        client=resolved_client,
        status="configured",
    )


def log_agent_event_to_langsmith(
    *,
    run: RunRecord,
    event: AgentEventRecord,
) -> LangSmithLogResult:
    return build_langsmith_tracker().log_agent_event(run=run, event=event)


def log_evaluation_to_langsmith(
    *,
    run: RunRecord,
    evaluation: EvaluationResultRecord,
) -> LangSmithLogResult:
    return build_langsmith_tracker().log_evaluation(run=run, evaluation=evaluation)


def _agent_event_metadata(
    config: LangSmithTrackingConfig,
    run: RunRecord,
    event: AgentEventRecord,
) -> dict[str, Any]:
    payload = event.payload
    metadata: dict[str, Any] = {
        "aeai.run_id": run.id,
        "aeai.trace_id": run.trace_id,
        "aeai.graph_node_id": event.node_id,
        "aeai.event_id": event.id,
        "aeai.event_type": str(event.event_type),
        "aeai.agent_name": payload.get("agent"),
        "aeai.artifact_ids": _artifact_ids(payload),
        "aeai.run_status": str(run.status),
    }
    metadata.update({f"tag.{key}": value for key, value in config.tags.items()})
    return _drop_empty(metadata)


def _evaluation_metadata(
    config: LangSmithTrackingConfig,
    run: RunRecord,
    evaluation: EvaluationResultRecord,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "aeai.run_id": run.id,
        "aeai.trace_id": run.trace_id,
        "aeai.graph_node_id": "evaluation",
        "aeai.agent_name": "evaluation",
        "aeai.evaluation_id": evaluation.id,
        "aeai.target_artifact_id": evaluation.target_artifact_id,
        "aeai.artifact_ids": (
            [evaluation.target_artifact_id] if evaluation.target_artifact_id else []
        ),
        "aeai.evaluation_score": evaluation.score,
        "aeai.evaluation_passed": evaluation.passed,
        "aeai.evaluation_check_count": len(evaluation.checks),
        "aeai.run_status": str(run.status),
    }
    metadata.update({f"tag.{key}": value for key, value in config.tags.items()})
    return _drop_empty(metadata)


def _finish_langsmith_run(
    client: Any,
    run_id: UUID,
    *,
    outputs: dict[str, Any],
    end_time: datetime | None,
) -> None:
    if hasattr(client, "update_run"):
        client.update_run(run_id, outputs=outputs, end_time=end_time)


def _stable_langsmith_id(kind: str, run_id: str, record_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"aeai-os:{kind}:{run_id}:{record_id}")


def _run_name(config: LangSmithTrackingConfig, *parts: str) -> str:
    clean_parts = [part.strip() for part in parts if part and part.strip()]
    return "-".join([config.run_name_prefix, *clean_parts])


def _tags(config: LangSmithTrackingConfig, *parts: str) -> list[str]:
    tags = ["aeai-os", *[part for part in parts if part]]
    tags.extend(f"{key}:{value}" for key, value in config.tags.items())
    return tags


def _client_kwargs(config: LangSmithTrackingConfig) -> dict[str, str]:
    kwargs = {"api_key": config.api_key or ""}
    if config.endpoint:
        kwargs["api_url"] = config.endpoint
    return kwargs


def _artifact_ids(payload: Mapping[str, Any]) -> list[str]:
    artifact_ids: list[str] = []
    for key in (
        "artifact_id",
        "artifact_ids",
        "artifacts",
        "target_artifact_id",
        "source_artifact_ids",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            artifact_ids.append(value)
        elif isinstance(value, list | tuple):
            artifact_ids.extend(str(item) for item in value if item)
    return sorted(set(artifact_ids))


def _drop_empty(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if value is not None and value != "" and value != []
    }


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_tags(value: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in value.split(","):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        normalized_key = key.strip()
        if normalized_key:
            tags[normalized_key] = raw_value.strip()
    return tags

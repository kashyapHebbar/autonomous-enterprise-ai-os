from __future__ import annotations

import importlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aeai_os.runs.models import EvaluationResultRecord, RunRecord


@dataclass(frozen=True)
class MLflowTrackingConfig:
    enabled: bool = False
    tracking_uri: str | None = None
    experiment_name: str = "Autonomous Enterprise AI OS"
    run_name_prefix: str = "aeai-run"
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MLflowLogResult:
    status: str
    message: str | None = None


class MLflowTracker:
    def __init__(
        self,
        *,
        config: MLflowTrackingConfig,
        client: Any | None = None,
        status: str,
        message: str | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.status = status
        self.message = message

    def log_evaluation(
        self,
        *,
        run: RunRecord,
        evaluation: EvaluationResultRecord,
    ) -> MLflowLogResult:
        if self.status != "configured" or self._client is None:
            return MLflowLogResult(status=self.status, message=self.message)

        try:
            _configure_client(self._client, self.config)
            tags = _evaluation_tags(self.config, run, evaluation)
            with self._client.start_run(
                run_name=f"{self.config.run_name_prefix}-{run.id}",
                tags=tags,
            ):
                self._client.log_params(_evaluation_params(run, evaluation))
                self._client.log_metrics(_evaluation_metrics(evaluation))
        except Exception as exc:  # pragma: no cover - exercised through fake clients in tests
            return MLflowLogResult(status="failed", message=str(exc))

        return MLflowLogResult(status="logged")


def build_mlflow_tracking_config(
    env: Mapping[str, str] | None = None,
) -> MLflowTrackingConfig:
    values = os.environ if env is None else env
    return MLflowTrackingConfig(
        enabled=_parse_bool(values.get("AEAI_MLFLOW_TRACKING_ENABLED"), default=False),
        tracking_uri=(
            values.get("AEAI_MLFLOW_TRACKING_URI") or values.get("MLFLOW_TRACKING_URI") or None
        ),
        experiment_name=(
            values.get("AEAI_MLFLOW_EXPERIMENT_NAME") or "Autonomous Enterprise AI OS"
        ),
        run_name_prefix=values.get("AEAI_MLFLOW_RUN_NAME_PREFIX") or "aeai-run",
        tags=_parse_tags(values.get("AEAI_MLFLOW_TAGS") or ""),
    )


def build_mlflow_tracker(
    config: MLflowTrackingConfig | None = None,
    *,
    mlflow_module: Any | None = None,
    importer: Callable[[str], Any] = importlib.import_module,
) -> MLflowTracker:
    resolved_config = config or build_mlflow_tracking_config()
    if not resolved_config.enabled:
        return MLflowTracker(config=resolved_config, status="disabled")

    client = mlflow_module
    if client is None:
        try:
            client = importer("mlflow")
        except ImportError:
            return MLflowTracker(
                config=resolved_config,
                status="unavailable",
                message=(
                    "MLflow tracking requested but the optional mlflow package is not installed."
                ),
            )

    return MLflowTracker(config=resolved_config, client=client, status="configured")


def log_evaluation_to_mlflow(
    *,
    run: RunRecord,
    evaluation: EvaluationResultRecord,
) -> MLflowLogResult:
    return build_mlflow_tracker().log_evaluation(run=run, evaluation=evaluation)


def _configure_client(client: Any, config: MLflowTrackingConfig) -> None:
    if config.tracking_uri and hasattr(client, "set_tracking_uri"):
        client.set_tracking_uri(config.tracking_uri)
    if config.experiment_name and hasattr(client, "set_experiment"):
        client.set_experiment(config.experiment_name)


def _evaluation_tags(
    config: MLflowTrackingConfig,
    run: RunRecord,
    evaluation: EvaluationResultRecord,
) -> dict[str, str]:
    tags = dict(config.tags)
    tags.update(
        {
            "aeai.run_id": run.id,
            "aeai.trace_id": run.trace_id or "",
            "aeai.evaluation_id": evaluation.id,
        }
    )
    return {key: value for key, value in tags.items() if value}


def _evaluation_params(
    run: RunRecord,
    evaluation: EvaluationResultRecord,
) -> dict[str, str]:
    return {
        "aeai.run_id": run.id,
        "aeai.trace_id": run.trace_id or "",
        "aeai.run_status": str(run.status),
        "aeai.task": run.task,
        "aeai.evaluation_id": evaluation.id,
        "aeai.target_artifact_id": evaluation.target_artifact_id or "",
    }


def _evaluation_metrics(evaluation: EvaluationResultRecord) -> dict[str, float]:
    metrics = {
        "evaluation_score": float(evaluation.score),
        "evaluation_passed": 1.0 if evaluation.passed else 0.0,
        "evaluation_check_count": float(len(evaluation.checks)),
    }
    for check in evaluation.checks:
        raw_name = str(check.get("name") or "unnamed")
        name = _metric_key(raw_name)
        if "score" in check:
            metrics[f"evaluation_check_{name}_score"] = float(check["score"])
        if "passed" in check:
            metrics[f"evaluation_check_{name}_passed"] = 1.0 if check["passed"] else 0.0
    return metrics


def _metric_key(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower()).strip("_")
    return normalized or "unnamed"


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

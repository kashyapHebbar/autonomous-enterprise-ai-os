"""Governed scheduled checks on already-registered sources.

Scheduled analysis uses the established deterministic workflow engine. Unless
explicitly opted in at the worker boundary, neither the schedule nor report
step calls a hosted model. Alerts are summaries, not accusations.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aeai_os.data.sources import DataSourceRegistry
from aeai_os.monitoring.store import MonitorStore
from aeai_os.schemas.enums import ArtifactType, RunStatus
from aeai_os.workflows.dynamic import execute_dynamic_workflow


@dataclass(frozen=True)
class RemoteSnapshot:
    id: str
    dataset_uri: str
    source_type: str = "local_file"

    @property
    def name(self) -> str:
        return Path(urlsplit(self.id).path).name or self.id

    def dataset_metadata(self) -> dict:
        return {
            "source": "reference",
            "format": Path(self.dataset_uri).suffix.lstrip("."),
            "monitoring_source": "s3_read_only_snapshot",
        }


def allowed_s3_reference(uri: str) -> tuple[str, str]:
    """Validate an allowlisted, direct S3 object reference. No arbitrary URLs."""
    parsed = urlsplit(uri)
    if (
        parsed.scheme != "s3"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Expected a direct s3://bucket/path.csv reference.")
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    allowed = {
        item.strip()
        for item in os.getenv("AEAI_MONITOR_S3_ALLOWED_BUCKETS", "").split(",")
        if item.strip()
    }
    if not allowed or bucket not in allowed:
        raise ValueError("S3 bucket is not allowlisted for monitoring.")
    if not key or len(key) > 450 or not re.fullmatch(r"[A-Za-z0-9/_=.,+@ -]+", key):
        raise ValueError("Invalid S3 object key")
    if (
        ".." in Path(key).parts
        or key.startswith("/")
        or Path(key).suffix.lower() not in {".csv", ".tsv"}
    ):
        raise ValueError("S3 monitoring accepts CSV/TSV objects only")
    return bucket, key


def download_s3_snapshot(uri: str, artifact_root: Path) -> RemoteSnapshot:
    """Read-only IAM S3 access, 50MB cap, atomic local snapshot, no credentials stored."""
    bucket, key = allowed_s3_reference(uri)
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        raise ValueError("Install boto3 to enable read-only S3 monitoring") from None
    client = boto3.client("s3")
    size = client.head_object(Bucket=bucket, Key=key).get("ContentLength")
    if not isinstance(size, int) or size > 50 * 1024 * 1024 or size < 1:
        raise ValueError("S3 source must be nonempty and no larger than 50 MB")
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    folder = artifact_root / "monitor-inputs"
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    downloaded = 0
    descriptor, temporary = tempfile.mkstemp(prefix=".s3-snapshot-", dir=folder)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            while True:
                chunk = body.read(min(1024 * 1024, 50 * 1024 * 1024 - downloaded + 1))
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > 50 * 1024 * 1024:
                    raise ValueError("S3 download exceeds monitoring size limit")
                digest.update(chunk)
                handle.write(chunk)
        extension = Path(key).suffix.lower()
        destination = folder / (digest.hexdigest() + extension)
        if destination.is_symlink():
            raise ValueError("Refusing an S3 snapshot destination symlink")
        if not destination.exists():
            os.replace(temporary, destination)
        os.chmod(destination, 0o600)
        return RemoteSnapshot(id=uri, dataset_uri=str(destination))
    finally:
        Path(temporary).unlink(missing_ok=True)
        body.close()


def fingerprint_source(source: Any) -> str:
    """Fingerprint bounded local files; no external connections during scans."""
    if source.source_type != "local_file":
        raise ValueError(
            "Scheduled execution currently requires a registered local CSV/TSV source."
        )
    path = Path(source.dataset_uri).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in {".csv", ".tsv"}:
        raise ValueError("Scheduled monitoring requires an existing CSV/TSV file.")
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Scheduled dataset exceeds the 50 MB monitoring limit.")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def extract_metrics(analysis: dict, quality: dict | None = None) -> dict[str, float]:
    kpis = analysis.get("kpis", {})
    if not isinstance(kpis, dict):
        return {}
    result = {}
    for key in (
        "total_spend",
        "anomaly_count",
        "high_risk_count",
        "row_count",
        "outlier_count",
        "completeness",
        "estimated_savings",
        "duplicate_row_count",
    ):
        num = _num(kpis.get(key))
        if num is not None:
            result[key] = round(num, 5)
    if "completeness" not in result and quality:
        rows = _num(quality.get("row_count"))
        columns = _num(quality.get("column_count"))
        missing = _num(quality.get("missing_cells"))
        if rows is not None and columns is not None and missing is not None:
            cells = rows * columns
            if cells > 0 and 0 <= missing <= cells:
                result["completeness"] = round(1 - missing / cells, 5)
    return result


def evaluate_thresholds(monitor: dict, current: dict, previous: dict | None) -> list[dict]:
    alerts: list[dict] = []
    anomalies = current.get("anomaly_count")
    if anomalies is not None and anomalies >= monitor["anomaly_limit"]:
        alerts.append(
            {
                "rule": "anomalies",
                "severity": "high" if anomalies >= monitor["anomaly_limit"] * 3 else "medium",
                "title": "Transactions need review",
                "description": "The saved analysis flagged transactions for manual verification.",
                "evidence": {"anomaly_count": anomalies, "threshold": monitor["anomaly_limit"]},
            }
        )
    completeness = current.get("completeness")
    if completeness is not None and completeness < monitor["minimum_completeness"]:
        alerts.append(
            {
                "rule": "completeness",
                "severity": "medium",
                "title": "Dataset quality below target",
                "description": "The calculated data completeness is below the configured threshold.",  # noqa: E501
                "evidence": {
                    "completeness": completeness,
                    "threshold": monitor["minimum_completeness"],
                },
            }
        )
    if previous is not None:
        old, new = previous.get("total_spend"), current.get("total_spend")
        if old is not None and new is not None and old > 0:
            pct = round(100 * (new - old) / old, 2)
            if abs(pct) >= monitor["spend_change_pct"]:
                alerts.append(
                    {
                        "rule": "spend_change",
                        "severity": "high" if abs(pct) >= 50 else "medium",
                        "title": "Spending changed significantly",
                        "description": "Compare the two completed analyses to verify the change and its cause.",  # noqa: E501
                        "evidence": {
                            "previous_total": old,
                            "current_total": new,
                            "change_pct": pct,
                            "threshold_pct": monitor["spend_change_pct"],
                        },
                    }
                )
    return alerts


def optional_ai_review(monitor: dict, alerts: list[dict], metrics: dict, dispatch_id: str) -> dict:
    """One optional budgeted HF call after deterministic evidence reveals an issue.

    The model sees only whitelisted numeric summaries and neutral rule labels.
    It cannot change alerts or figures. Failure never causes a retry loop.
    """
    if not alerts or not monitor["ai_escalation"]:
        return {}
    if os.getenv("AEAI_MONITOR_AI_ESCALATION_ENABLED", "").strip().lower() not in {
        "true",
        "1",
        "yes",
    }:
        return {}
    from aeai_os.llm.budget import BudgetPolicy, llm_usage_scope
    from aeai_os.llm.gateway import HuggingFaceChatGateway, LLMError
    from aeai_os.settings import get_settings

    settings = get_settings()
    if not settings.llm_api_key or settings.llm_provider not in {"huggingface", "hf"}:
        return {"status": "skipped", "reason": "HF token/provider not configured"}
    schema = {
        "type": "object",
        "properties": {
            "interpretation": {"type": "string"},
            "recommended_next_step": {"type": "string"},
        },
        "required": ["interpretation", "recommended_next_step"],
        "additionalProperties": False,
    }
    # Budget cap per alert review <= $0.01, one model request, monthly shared ledger.
    policy = replace(
        BudgetPolicy.from_settings(settings),
        workflow_usd=min(0.01, settings.llm_workflow_budget_usd),
        max_calls=1,
        max_output_tokens=min(500, settings.llm_max_output_tokens),
    )
    try:
        gateway = HuggingFaceChatGateway(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        facts = {
            key: metrics[key]
            for key in ("anomaly_count", "total_spend", "completeness")
            if key in metrics
        }
        request = {"triggered_rules": [a["rule"] for a in alerts[:3]], "verified_metrics": facts}
        import json

        with llm_usage_scope(dispatch_id, policy) as tracker:
            data = gateway.generate(
                instructions="Briefly interpret a verified enterprise alert. Avoid numbers and unsupported claims. "  # noqa: E501
                "No accusations, account names, raw records, actions or new calculations. "
                "Suggest manual review only. Output structured JSON.",
                input_text=json.dumps(request, separators=(",", ":")),
                schema=schema,
                schema_name="enterprise_monitor_alert_review",
                max_output_tokens=500,
            )
            interpretation = data.get("interpretation")
            next_step = data.get("recommended_next_step")
            if not all(
                isinstance(text, str)
                and 8 <= len(text) <= 400
                and not any(ch.isdigit() for ch in text)
                for text in (interpretation, next_step)
            ):
                raise ValueError("AI alert review did not meet evidence policy")
            return {
                "status": "created",
                "interpretation": interpretation,
                "recommended_next_step": next_step,
                "model": gateway.model,
                "estimated_cost_usd": tracker.snapshot()["estimated_cost_usd"],
            }
    except (LLMError, ValueError, OSError):
        return {
            "status": "unavailable",
            "reason": "AI review could not be validated; deterministic alert remains",
        }


def execute_claim(
    monitor: dict,
    *,
    store: MonitorStore,
    registry: DataSourceRegistry,
    repository: Any,
    artifact_store: Any,
    artifact_root: Path,
    execute_fn=execute_dynamic_workflow,
) -> dict:
    """Process one atomically claimed monitor with idempotent inputs and no raw-data alerts."""
    run_id = None
    fingerprint = None
    try:
        source = (
            download_s3_snapshot(monitor["source_id"], artifact_root)
            if monitor["source_id"].startswith("s3://")
            else registry.validate_for_execution(
                monitor["source_id"], monitor["organization_id"], monitor["workspace_id"]
            )
        )
        fingerprint = fingerprint_source(source)
        if (
            monitor["only_on_change"]
            and not monitor["force_once"]
            and fingerprint == monitor["last_fingerprint"]
        ):
            store.finish(monitor, status="skipped", fingerprint=fingerprint)
            return {"status": "skipped", "reason": "No changes in registered dataset"}
        previous = store.last_completed(monitor["id"])
        run = repository.create_run(
            task=monitor["task"],
            metadata={
                "organization_id": monitor["organization_id"],
                "workspace_id": monitor["workspace_id"],
                "monitor_id": monitor["id"],
                "scheduled": True,
                "data_source_id": source.id,
                "data_source_name": source.name,
                "data_source_type": source.source_type,
            },
        )
        run_id = run.id
        repository.add_artifact(
            run_id=run_id,
            artifact_type=ArtifactType.DATASET,
            uri=source.dataset_uri,
            metadata=source.dataset_metadata(),
        )
        execute_fn(
            repository=repository,
            artifact_root=artifact_root,
            run_id=run_id,
            artifact_store=artifact_store,
        )
        finished = repository.get_run(run_id)
        if finished.status != RunStatus.COMPLETED:
            raise RuntimeError("Scheduled investigation did not complete successfully")
        source_artifact = next(
            (
                artifact
                for artifact in reversed(repository.list_artifacts(run_id))
                if artifact.type == ArtifactType.KPI_TABLE
                and artifact.metadata.get("source") == "analytics_code_agent"
                and artifact.metadata.get("format") == "json"
            ),
            None,
        )
        if source_artifact is None:
            raise RuntimeError("Completed run did not produce a verified analytics artifact")
        analysis = artifact_store.read_json(source_artifact.uri)
        quality_artifact = next(
            (
                artifact
                for artifact in reversed(repository.list_artifacts(run_id))
                if artifact.type == ArtifactType.QUALITY_REPORT
                and artifact.metadata.get("source") == "data_retrieval_agent"
                and artifact.metadata.get("format") == "json"
            ),
            None,
        )
        quality = artifact_store.read_json(quality_artifact.uri) if quality_artifact else None
        metrics = extract_metrics(analysis, quality)
        if not metrics:
            raise RuntimeError("No supported KPI metrics were available")
        previous_metrics = previous["metrics"] if previous else None
        alerts = evaluate_thresholds(monitor, metrics, previous_metrics)
        for alert in alerts:
            store.create_alert(monitor, run_id=run_id, **alert)
        ai_review = optional_ai_review(monitor, alerts, metrics, monitor["dispatch_id"])
        store.finish(
            monitor,
            status="completed",
            fingerprint=fingerprint,
            run_id=run_id,
            metrics=metrics,
            ai_review=ai_review,
        )
        return {"status": "completed", "run_id": run_id, "alerts": len(alerts), "metrics": metrics}
    except Exception as exc:
        # Never persist stack traces, credentials, dataset contents or raw SQL in alerts.
        error = type(exc).__name__
        store.finish(
            monitor,
            status="failed",
            fingerprint=fingerprint,
            run_id=run_id,
            error=f"Scheduled check failed ({error}). Review backend logs.",
        )
        store.create_alert(
            monitor,
            rule="execution_failure",
            severity="high",
            title="Scheduled investigation could not complete",
            description="Check the monitoring worker logs and the registered data source.",
            evidence={"error_type": error},
            run_id=run_id,
        )
        return {"status": "failed", "run_id": run_id, "error_type": error}


def process_due(
    *,
    store: MonitorStore,
    registry: DataSourceRegistry,
    repository: Any,
    artifact_store: Any,
    artifact_root: Path,
    max_claims: int = 2,
) -> list[dict]:
    return [
        execute_claim(
            item,
            store=store,
            registry=registry,
            repository=repository,
            artifact_store=artifact_store,
            artifact_root=artifact_root,
        )
        for item in store.claim(limit=max_claims)
    ]

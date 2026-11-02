"""Streaming CSV financial reconciliation (no pandas, LLM or full-row materialization).

This is an *independent source-to-KPI check*, not proof of statistical
accuracy, procurement fraud, or correctness of all downstream insights.
"""

from __future__ import annotations

import csv
import os
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from aeai_os.runs.models import AgentEventRecord
from aeai_os.runs.repository import utc_now
from aeai_os.schemas.enums import AgentEventType, ArtifactType

DEFAULT_MAX_ROWS = 500_000


def _amount(value: Any) -> Decimal | None:
    """Match the current procurement engine's accepted monetary input forms."""
    if value is None or str(value).strip().lower() in {"", "na", "n/a", "nan", "none", "null"}:
        return None
    text = str(value).strip().replace(",", "")
    text = text.translate(str.maketrans("", "", "$£€¥₹"))
    try:
        number = Decimal(text)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def _close(actual: Decimal, reported: Any) -> bool:
    try:
        stated = Decimal(str(reported))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not stated.is_finite():
        return False
    # Accommodate original float accumulation and four-place KPI rounding.
    return abs(actual - stated) <= max(Decimal("0.01"), abs(actual) * Decimal("0.00000001"))


def stream_reconcile(
    path: Path, analysis: dict[str, Any], *, max_rows: int = DEFAULT_MAX_ROWS
) -> dict[str, Any]:
    if not 1 <= max_rows <= 2_000_000:
        raise ValueError("Audit row cap must be between 1 and 2,000,000.")
    started = time.perf_counter()
    before = path.stat()
    if path.suffix.lower() != ".csv" or not path.is_file():
        return {
            "status": "skipped",
            "reason": "Only existing local CSV files are independently checked.",
        }
    resolved = (analysis.get("dataset") or {}).get("resolved_columns") or {}
    amount_name, supplier_name, category_name = (
        resolved.get(key) for key in ("amount", "supplier", "category")
    )
    if not all(
        isinstance(item, str) and item for item in (amount_name, supplier_name, category_name)
    ):
        return {"status": "skipped", "reason": "Saved procurement column mapping is incomplete."}
    row_count = 0
    valid_amounts = 0
    exact_total = Decimal(0)
    supplier_totals: dict[str, Decimal] = defaultdict(Decimal)
    category_totals: dict[str, Decimal] = defaultdict(Decimal)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        raw_fields = {str(name).strip(): name for name in reader.fieldnames or []}
        if not {amount_name, supplier_name, category_name}.issubset(raw_fields):
            return {
                "status": "failed",
                "reason": "The CSV header no longer matches the saved analysis.",
            }
        for row in reader:
            row_count += 1
            if row_count > max_rows:
                return {
                    "status": "skipped",
                    "reason": "Audit row limit reached; raise AEAI_AUDIT_MAX_ROWS cautiously.",
                    "rows_scanned": max_rows,
                    "limit": max_rows,
                }
            amount = _amount(row.get(raw_fields[amount_name]))
            if amount is None:
                continue
            valid_amounts += 1
            exact_total += amount
            supplier_totals[(row.get(raw_fields[supplier_name]) or "").strip() or "<missing>"] += (
                amount
            )
            category_totals[(row.get(raw_fields[category_name]) or "").strip() or "<missing>"] += (
                amount
            )
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        return {
            "status": "failed",
            "reason": "Input CSV changed during verification.",
            "rows_scanned": row_count,
        }
    dataset = analysis.get("dataset") or {}
    kpis = analysis.get("kpis") or {}
    checks = {
        "row_count": row_count == dataset.get("row_count"),
        "valid_amount_rows": valid_amounts == dataset.get("valid_amount_rows"),
        "total_spending": _close(exact_total, kpis.get("total_spend")),
        "supplier_count": len(supplier_totals) == kpis.get("supplier_count"),
        "category_count": len(category_totals) == kpis.get("category_count"),
    }
    # Reconcile full aggregate breakdown, not only the headline total.
    for label, computed, key in (
        ("supplier_breakdown", supplier_totals, "spend_by_supplier"),
        ("category_breakdown", category_totals, "spend_by_category"),
    ):
        saved_rows = analysis.get(key) or []
        if not isinstance(saved_rows, list):
            checks[label] = False
            continue
        field = "supplier" if label.startswith("supplier") else "category"
        reported = {
            item.get(field): item.get("spend") for item in saved_rows if isinstance(item, dict)
        }
        checks[label] = len(reported) == len(computed) and all(
            item in reported and _close(amount, reported[item]) for item, amount in computed.items()
        )
    return {
        "status": "verified" if all(checks.values()) else "mismatch",
        "rows_scanned": row_count,
        "source_size_bytes": before.st_size,
        "valid_amount_rows": valid_amounts,
        "independently_calculated_total": round(float(exact_total), 4),
        "reported_total": kpis.get("total_spend"),
        "checks": checks,
        "checks_passed": sum(checks.values()),
        "checks_total": len(checks),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "note": "Independent streaming reconciliation of saved procurement KPIs; not fraud validation or full analytical accuracy.",  # noqa: E501
    }


def verify_run(
    repository: Any, artifact_store: Any, run_id: str, *, max_rows: int | None = None
) -> dict[str, Any]:
    """Record one audit event. Never call an LLM or mutate source data."""
    if max_rows is None:
        try:
            max_rows = int(os.environ.get("AEAI_AUDIT_MAX_ROWS", str(DEFAULT_MAX_ROWS)))
        except ValueError:
            max_rows = DEFAULT_MAX_ROWS
    run = repository.get_run(run_id)
    if not run.dataset_artifact_id:
        summary = {"status": "skipped", "reason": "No linked dataset."}
    else:
        dataset = repository.get_artifact(run_id, run.dataset_artifact_id)
        source = next(
            (
                artifact
                for artifact in reversed(repository.list_artifacts(run_id))
                if artifact.type == ArtifactType.KPI_TABLE
                and artifact.metadata.get("source") == "analytics_code_agent"
            ),
            None,
        )
        if source is None:
            summary = {"status": "skipped", "reason": "No saved numerical analysis."}
        else:
            try:
                analysis = artifact_store.read_json(source.uri)
                if analysis.get("analysis_type") != "procurement":
                    summary = {
                        "status": "skipped",
                        "reason": "Independent verification currently supports procurement CSVs.",
                    }
                elif urlparse(dataset.uri).scheme not in ("", "file"):
                    summary = {
                        "status": "skipped",
                        "reason": "Remote and warehouse inputs require a separately configured source snapshot.",  # noqa: E501
                    }
                else:
                    path = Path(
                        urlparse(dataset.uri).path
                        if dataset.uri.startswith("file:")
                        else dataset.uri
                    )
                    summary = stream_reconcile(path, analysis, max_rows=max_rows)
            except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
                summary = {
                    "status": "unavailable",
                    "reason": "Audit could not complete.",
                    "error_type": type(exc).__name__,
                }
    repository.add_event(
        AgentEventRecord(
            id=f"event_{uuid4().hex}",
            run_id=run_id,
            node_id="evidence_verification",
            event_type=AgentEventType.LOG.value,
            payload={
                "message": "Independent source-to-KPI reconciliation recorded.",
                "verification_summary": summary,
            },
            created_at=utc_now(),
        )
    )
    return summary


def check_local_csv_capacity(path: Path, *, max_mib: int | None = None) -> None:
    """Fail before the existing eager profiler allocates an excessive row list.

    This guard is deliberately conservative and configurable: it protects local
    development machines; it is not a claim of larger-dataset scalability.
    """
    if max_mib is None:
        try:
            max_mib = int(os.environ.get("AEAI_MAX_SOURCE_CSV_MIB", "96"))
        except ValueError:
            max_mib = 96
    if not 1 <= max_mib <= 1024:
        raise ValueError("AEAI_MAX_SOURCE_CSV_MIB must be between 1 and 1024.")
    if path.suffix.lower() == ".csv" and path.stat().st_size > max_mib * 1024 * 1024:
        raise ValueError(
            "This CSV exceeds the configured safe in-memory analysis size. "
            "Use a representative sample, run scripts/benchmark_dataset.py, "
            "or increase AEAI_MAX_SOURCE_CSV_MIB only after measuring available RAM."
        )

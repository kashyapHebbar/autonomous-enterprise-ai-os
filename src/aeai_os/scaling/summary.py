"""Exact, streaming spend aggregates; deliberately *not* an anomaly/risk engine.

Only stable, aggregate metrics cross the API boundary. The scanner never sends
source rows to Hugging Face, runs user SQL/code, or modifies the original CSV.
"""

from __future__ import annotations

import csv
import os
import time
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from aeai_os.analytics.kpis import _parse_month, _resolve_columns


class ScalingError(ValueError):
    """User-actionable scan limit or invalid-source error."""


def _integer_setting(name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ScalingError(f"{name} must be an integer.") from exc
    if not lower <= value <= upper:
        raise ScalingError(f"{name} must be between {lower} and {upper}.")
    return value


def _money(raw: Any) -> Decimal | None:
    if raw is None or str(raw).strip().lower() in {"", "none", "na", "n/a", "null", "nan"}:
        return None
    text = str(raw).strip().replace(",", "")
    text = text.translate(str.maketrans("", "", "$£€₹¥"))
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def _top_groups(
    totals: dict[str, Decimal], counts: dict[str, int], total: Decimal, *, limit: int = 20
) -> dict[str, Any]:
    visible = [
        (name, value)
        for name, value in totals.items()
        if counts[name] >= 2  # Follow the existing dashboard's small-cohort suppression.
    ]
    visible.sort(key=lambda item: (-item[1], item[0]))
    result = [
        {
            "name": name,
            "spend": round(float(value), 4),
            "transactions": counts[name],
            "share_of_total": round(float(value / total), 6) if total else 0.0,
        }
        for name, value in visible[:limit]
    ]
    return {
        "groups_total": len(totals),
        "groups_eligible": len(visible),
        "groups_suppressed": len(totals) - len(visible),
        "groups_shown": len(result),
        "items": result,
        "coverage_note": "Only groups with at least two valid-amount transactions appear; top groups are not the full total.",  # noqa: E501
    }


def stream_financial_summary(path: str | Path, *, row_limit: int | None = None) -> dict[str, Any]:
    """Scan a local CSV in constant row-memory and bounded group-memory.

    Entire file is read for totals. Supplier/category dimension distinct keys
    are capped explicitly; exceeding cap stops with an error rather than
    claiming that a partial aggregation is complete.
    """
    csv_path = Path(path).expanduser()
    if csv_path.suffix.lower() != ".csv" or not csv_path.is_file():
        raise ScalingError(
            "Choose a registered local CSV file; remote/warehouse sources are not supported here."
        )
    max_rows = row_limit or _integer_setting("AEAI_SCALING_MAX_ROWS", 1_000_000, 1, 5_000_000)
    max_mib = _integer_setting("AEAI_SCALING_MAX_MIB", 512, 1, 4096)
    group_limit = _integer_setting("AEAI_SCALING_MAX_GROUPS", 50_000, 100, 500_000)
    max_seconds = _integer_setting("AEAI_SCALING_MAX_SECONDS", 120, 5, 1800)
    original = csv_path.stat()
    if original.st_size > max_mib * 1024 * 1024:
        raise ScalingError("File exceeds AEAI_SCALING_MAX_MIB; do not silently sample it.")
    started = time.perf_counter()
    row_count = valid_amounts = invalid_amounts = dated_rows = missing_cells = 0
    amount_total = Decimal(0)
    suppliers: dict[str, Decimal] = defaultdict(Decimal)
    categories: dict[str, Decimal] = defaultdict(Decimal)
    supplier_counts: dict[str, int] = defaultdict(int)
    category_counts: dict[str, int] = defaultdict(int)
    months: dict[str, Decimal] = defaultdict(Decimal)
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        raw_fields = reader.fieldnames or []
        fields = [field.strip() for field in raw_fields]
        if not fields or any(not field for field in fields) or len(set(fields)) != len(fields):
            raise ScalingError("CSV header is empty, duplicated or contains blank column names.")
        roles = _resolve_columns(fields)
        required = {"supplier", "category", "amount"}
        if not required.issubset(roles):
            raise ScalingError("Procurement overview needs supplier, category and amount columns.")
        raw_names = dict(zip(fields, raw_fields, strict=True))
        for row in reader:
            row_count += 1
            if row_count > max_rows:
                raise ScalingError(
                    "Row limit reached; no partial totals were saved. Increase AEAI_SCALING_MAX_ROWS only after benchmarking."  # noqa: E501
                )
            if row_count % 10_000 == 0 and time.perf_counter() - started > max_seconds:
                raise ScalingError("Scan exceeded time limit; no partial totals were saved.")
            missing_cells += sum(not str(row.get(raw) or "").strip() for raw in raw_fields)
            amount = _money(row.get(raw_names[roles["amount"]]))
            if amount is None:
                invalid_amounts += 1
                continue
            valid_amounts += 1
            amount_total += amount
            supplier = str(row.get(raw_names[roles["supplier"]]) or "").strip() or "<missing>"
            category = str(row.get(raw_names[roles["category"]]) or "").strip() or "<missing>"
            if supplier not in suppliers and len(suppliers) >= group_limit:
                raise ScalingError(
                    "Supplier cardinality exceeds safe grouping limit; no partial results saved."
                )
            if category not in categories and len(categories) >= group_limit:
                raise ScalingError(
                    "Category cardinality exceeds safe grouping limit; no partial results saved."
                )
            suppliers[supplier] += amount
            categories[category] += amount
            supplier_counts[supplier] += 1
            category_counts[category] += 1
            if roles.get("date"):
                month = _parse_month(str(row.get(raw_names[roles["date"]]) or ""))
                if month:
                    months[month] += amount
                    dated_rows += 1
                    if len(months) > 2400:
                        raise ScalingError(
                            "Unusual date cardinality; scan aborted rather than truncating periods."
                        )
    current = csv_path.stat()
    if (original.st_ino, original.st_size, original.st_mtime_ns) != (
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
    ):
        raise ScalingError("Source file changed during analysis; rerun against a stable snapshot.")
    if (
        sum(suppliers.values(), Decimal(0)) != amount_total
        or sum(categories.values(), Decimal(0)) != amount_total
    ):
        raise ScalingError("Internal financial reconciliation failed; no results saved.")
    timeline = [
        {"month": key, "spend": round(float(value), 4)} for key, value in sorted(months.items())
    ]
    return {
        "status": "completed",
        "analysis_type": "streaming_financial_overview",
        "coverage": "full_source_financial_aggregates_only",
        "data_limitations": [
            "No transaction-level anomaly, duplicate invoice, risk or savings analysis was performed.",  # noqa: E501
            "Suppressed single-transaction groups are excluded from the displayed ranked breakdowns.",  # noqa: E501
            "Amounts are aggregated as recorded; no currency conversion was performed.",
        ],
        "source": {"size_bytes": original.st_size, "last_modified_ns": original.st_mtime_ns},
        "column_roles": roles,
        "metrics": {
            "rows_scanned": row_count,
            "valid_amount_rows": valid_amounts,
            "invalid_amount_rows": invalid_amounts,
            "missing_cells": missing_cells,
            "column_count": len(fields),
            "total_spend": round(float(amount_total), 4),
            "supplier_count": len(suppliers),
            "category_count": len(categories),
            "dated_amount_rows": dated_rows,
        },
        "suppliers": _top_groups(suppliers, supplier_counts, amount_total),
        "categories": _top_groups(categories, category_counts, amount_total),
        "monthly_spend": timeline,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "verification": "Exact Decimal spending total reconciled against complete supplier and category sums.",  # noqa: E501
        "source_stable": True,
        "hugging_face_requests": 0,
    }

"""Read-only, run-scoped aggregates for interactive visualization.

This endpoint deliberately does not return transactions, identifiers, invoice details,
free-text fields, or small cohorts. It does not call any language model.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from aeai_os.agents.analyst_tools import load_run_aggregates

MAX_CELLS = 240
MIN_GROUP_SIZE = 2


def build_visualization_cube(
    dataset_uri: str, analysis: dict[str, Any], artifact_root
) -> dict[str, Any]:
    """Provide an explicitly partial, bounded cohort cube from an authorized local CSV.

    Each released cell contains at least two transactions. Suppressed cells never
    contribute to returned subtotals; no complete dimensions/totals are included,
    to avoid inferring singleton cells by subtraction. Only existing permitted
    semantic roles are used, and changed input datasets are rejected upstream.
    """
    dataset = load_run_aggregates(dataset_uri, analysis, artifact_root)
    available = {
        "supplier": bool(dataset["suppliers"]),
        "category": bool(dataset["categories"]),
        "department": bool(dataset["departments"]),
        "month": bool(dataset["months"]),
    }
    if not available["supplier"] and not available["category"]:
        return {
            "cells": [],
            "dimensions": [],
            "covered_transactions": 0,
            "suppressed_cells": 0,
            "note": "No compatible dimensions were detected.",
        }
    # Four-dimensional cohorts avoid relying on separately published marginal totals
    # when users select multiple filters. Month may be empty for undated rows.
    groups: dict[tuple[str, str, str, str], list[float | int]] = defaultdict(lambda: [0.0, 0])
    for supplier, category, department, month, amount in dataset["rows"]:
        if not math.isfinite(amount):
            continue
        key = (supplier or "", category or "", department or "", month or "")
        groups[key][0] += amount
        groups[key][1] += 1
    eligible = [
        (key, value, count) for key, (value, count) in groups.items() if count >= MIN_GROUP_SIZE
    ]
    # Do not truncate cells: doing so would silently alter filtered metrics.
    if len(eligible) > MAX_CELLS:
        return {
            "cells": [],
            "dimensions": [k for k, v in available.items() if v],
            "covered_transactions": 0,
            "suppressed_cells": len(groups),
            "note": "Too many grouped combinations for safe, complete visualization. Use saved overview charts.",  # noqa: E501
        }
    eligible.sort(key=lambda entry: entry[0])
    return {
        "cells": [
            {
                **dict(zip(("supplier", "category", "department", "month"), key, strict=True)),
                "amount": round(float(value), 4),
                "transactions": int(count),
            }
            for key, value, count in eligible
        ],
        "dimensions": [k for k, v in available.items() if v],
        "covered_transactions": sum(int(count) for _, _, count in eligible),
        "suppressed_cells": sum(int(count) < MIN_GROUP_SIZE for _, count in groups.values()),
        "note": (
            "Privacy-safe cohort data only: each visible combination contains at least two "
            "transactions. Other transactions are excluded from filtered charts. "
            "These subtotals must not be interpreted as the full dataset spending."
        ),
    }

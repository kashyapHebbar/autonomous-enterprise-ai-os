#!/usr/bin/env python3
"""Benchmark read-only streaming aggregates on a chosen local CSV (no API or LLM)."""

from __future__ import annotations

import argparse
import json
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aeai_os.scaling.summary import ScalingError, stream_financial_summary  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure CSV financial scan speed and Python peak allocation"
    )
    parser.add_argument(
        "file", type=Path, help="Existing local CSV with supplier, category and amount"
    )
    args = parser.parse_args()
    tracemalloc.start()
    try:
        result = stream_financial_summary(args.file)
    except (ScalingError, OSError) as exc:
        print(f"SCAN REJECTED: {exc}", file=sys.stderr)
        return 1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "status": result["status"],
                "rows_scanned": result["metrics"]["rows_scanned"],
                "total_spend": result["metrics"]["total_spend"],
                "duration_seconds": result["duration_seconds"],
                "rows_per_second": round(
                    result["metrics"]["rows_scanned"] / max(result["duration_seconds"], 0.001)
                ),
                "python_peak_allocated_mib": round(peak / 1024**2, 2),
                "scope": result["coverage"],
                "llm_calls": 0,
                "note": "Peak Python allocations are not total system RAM. This benchmark does not run anomaly detection.",  # noqa: E501
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

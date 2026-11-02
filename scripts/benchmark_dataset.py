#!/usr/bin/env python3
"""Offline, streaming CSV capacity benchmark; does not invoke agents or Hugging Face.

Use --max-rows 10000, 50000, 100000 to measure your *CSV read* throughput.
This is NOT a benchmark of a full analytic workflow or model inference.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import tracemalloc
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CSV scan performance benchmark")
    parser.add_argument("csv", type=Path, help="Local CSV file; no remote URL")
    parser.add_argument("--max-rows", type=int, default=10000)
    args = parser.parse_args()
    if args.max_rows < 1 or args.max_rows > 2_000_000:
        parser.error("--max-rows must be between 1 and 2,000,000")
    if not args.csv.is_file() or args.csv.suffix.lower() != ".csv":
        parser.error("Supply an existing local .csv file")
    rows = 0
    tracemalloc.start()
    started = time.perf_counter()
    try:
        with args.csv.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                parser.error("CSV file has no header")
            cols = len(reader.fieldnames)
            for _ in reader:
                rows += 1
                if rows >= args.max_rows:
                    break
    except (OSError, csv.Error, UnicodeError) as error:
        print(json.dumps({"status": "failed", "error_type": type(error).__name__}), file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "status": "scanned",
                "rows_scanned": rows,
                "columns": cols,
                "elapsed_seconds": round(elapsed, 3),
                "rows_per_second": round(rows / elapsed) if elapsed else None,
                "peak_traced_python_mib": round(peak / (1024**2), 2),
                "note": "Streaming CSV scan only. Full analytics can require substantially more memory.",  # noqa: E501
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

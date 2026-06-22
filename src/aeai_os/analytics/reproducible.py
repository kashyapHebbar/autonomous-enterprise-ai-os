from __future__ import annotations


def generate_reproducible_analysis_code() -> str:
    return '''#!/usr/bin/env python3
"""Reproduce core procurement spend summaries from a CSV file."""

import argparse
import csv
import json
from collections import defaultdict


def parse_amount(value):
    try:
        return float(value.replace(",", "").replace("$", "").strip())
    except (AttributeError, ValueError):
        return None


def analyze(csv_path):
    supplier_totals = defaultdict(float)
    category_totals = defaultdict(float)
    row_count = 0
    invalid_amount_rows = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            row_count += 1
            amount = parse_amount(row.get("spend_amount", ""))
            if amount is None:
                invalid_amount_rows += 1
                continue
            supplier = row.get("supplier", "").strip() or "<missing>"
            category = row.get("category", "").strip() or "<missing>"
            supplier_totals[supplier] += amount
            category_totals[category] += amount

    return {
        "row_count": row_count,
        "invalid_amount_rows": invalid_amount_rows,
        "total_spend": round(sum(supplier_totals.values()), 4),
        "spend_by_supplier": dict(sorted(supplier_totals.items())),
        "spend_by_category": dict(sorted(category_totals.items())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    args = parser.parse_args()
    print(json.dumps(analyze(args.csv_path), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
'''

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

MISSING_MARKERS = {"", "na", "n/a", "nan", "none", "null"}


class DataIngestionError(ValueError):
    pass


@dataclass(frozen=True)
class CsvColumnProfile:
    name: str
    inferred_type: str
    description: str
    missing_count: int
    missing_ratio: float
    unique_count: int
    example_values: list[str] = field(default_factory=list)
    summary_statistics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CsvDatasetProfile:
    path: str
    row_count: int
    column_count: int
    columns: list[CsvColumnProfile]
    quality_summary: dict[str, Any]

    def schema_artifact(self) -> dict[str, Any]:
        return {
            "source_path": self.path,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "columns": [
                {
                    "name": column.name,
                    "type": column.inferred_type,
                    "description": column.description,
                    "nullable": column.missing_count > 0,
                    "missing_count": column.missing_count,
                    "unique_count": column.unique_count,
                    "example_values": column.example_values,
                    "summary_statistics": column.summary_statistics,
                }
                for column in self.columns
            ],
        }

    def quality_artifact(self) -> dict[str, Any]:
        return {
            "source_path": self.path,
            "row_count": self.row_count,
            "column_count": self.column_count,
            **self.quality_summary,
        }


def profile_csv_dataset(path: str | Path) -> CsvDatasetProfile:
    csv_path = Path(path)
    if csv_path.suffix.lower() != ".csv":
        raise DataIngestionError(f"Unsupported dataset file type: {csv_path.suffix}")
    if not csv_path.exists():
        raise DataIngestionError(f"Dataset file does not exist: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise DataIngestionError("CSV dataset must include a header row.")
        raw_fieldnames = list(reader.fieldnames)
        fieldnames = [field.strip() for field in raw_fieldnames]
        if any(not field for field in fieldnames):
            raise DataIngestionError("CSV dataset contains a blank column name.")
        if len(fieldnames) != len(set(fieldnames)):
            raise DataIngestionError("CSV dataset contains duplicate column names.")
        rows = [
            {
                normalized: (row.get(raw) or "").strip()
                for raw, normalized in zip(raw_fieldnames, fieldnames, strict=True)
            }
            for row in reader
        ]

    columns = [_profile_column(field, rows) for field in fieldnames]
    missing_cells = sum(column.missing_count for column in columns)
    total_cells = len(rows) * len(fieldnames)
    duplicate_rows = _count_duplicate_rows(rows, fieldnames)
    columns_with_missing = [column.name for column in columns if column.missing_count]
    empty_columns = [column.name for column in columns if column.missing_count == len(rows)]
    warnings = _quality_warnings(
        row_count=len(rows),
        empty_columns=empty_columns,
        duplicate_row_count=duplicate_rows,
    )

    return CsvDatasetProfile(
        path=str(csv_path),
        row_count=len(rows),
        column_count=len(fieldnames),
        columns=columns,
        quality_summary={
            "missing_cells": missing_cells,
            "missing_cell_ratio": round(missing_cells / total_cells, 4) if total_cells else 0.0,
            "columns_with_missing": columns_with_missing,
            "empty_columns": empty_columns,
            "duplicate_row_count": duplicate_rows,
            "warnings": warnings,
        },
    )


def is_missing_value(value: str) -> bool:
    return value.strip().lower() in MISSING_MARKERS


def _profile_column(column_name: str, rows: list[dict[str, str]]) -> CsvColumnProfile:
    values = [row[column_name] for row in rows]
    non_missing = [value for value in values if not is_missing_value(value)]
    inferred_type = _infer_type(non_missing)
    examples = list(dict.fromkeys(non_missing[:10]))[:3]
    stats = _summary_statistics(non_missing) if inferred_type in {"integer", "number"} else {}
    missing_count = len(values) - len(non_missing)
    return CsvColumnProfile(
        name=column_name,
        inferred_type=inferred_type,
        description=_describe_column(column_name, inferred_type),
        missing_count=missing_count,
        missing_ratio=round(missing_count / len(values), 4) if values else 0.0,
        unique_count=len(set(non_missing)),
        example_values=examples,
        summary_statistics=stats,
    )


def _infer_type(values: list[str]) -> str:
    if not values:
        return "unknown"
    if all(_is_int(value) for value in values):
        return "integer"
    if all(_is_float(value) for value in values):
        return "number"
    if all(_is_bool(value) for value in values):
        return "boolean"
    if all(_is_date(value) for value in values):
        return "date"
    return "string"


def _summary_statistics(values: list[str]) -> dict[str, float]:
    numeric_values = [float(value.replace(",", "")) for value in values]
    return {
        "min": min(numeric_values),
        "max": max(numeric_values),
        "mean": round(mean(numeric_values), 4),
        "sum": round(sum(numeric_values), 4),
    }


def _describe_column(column_name: str, inferred_type: str) -> str:
    lowered = column_name.lower()
    if any(token in lowered for token in {"supplier", "vendor"}):
        return "Supplier or vendor dimension used for procurement spend grouping."
    if "category" in lowered:
        return "Procurement category dimension for spend segmentation."
    if any(token in lowered for token in {"amount", "spend", "cost", "price"}):
        return "Monetary procurement measure suitable for KPI aggregation."
    if "invoice" in lowered:
        return "Invoice identifier or invoice-level attribute."
    if "date" in lowered:
        return "Date field suitable for trend analysis."
    if "department" in lowered or "business_unit" in lowered:
        return "Organizational dimension for procurement ownership analysis."
    if "quantity" in lowered or "qty" in lowered:
        return "Quantity measure associated with purchased goods or services."
    return f"{inferred_type.title()} column from the uploaded dataset."


def _count_duplicate_rows(rows: list[dict[str, str]], fieldnames: list[str]) -> int:
    row_keys = [tuple(row[field] for field in fieldnames) for row in rows]
    counts = Counter(row_keys)
    return sum(count - 1 for count in counts.values() if count > 1)


def _quality_warnings(
    row_count: int,
    empty_columns: list[str],
    duplicate_row_count: int,
) -> list[str]:
    warnings: list[str] = []
    if row_count == 0:
        warnings.append("Dataset contains no rows.")
    if empty_columns:
        warnings.append(f"Columns with no observed values: {', '.join(empty_columns)}.")
    if duplicate_row_count:
        warnings.append(f"Detected {duplicate_row_count} duplicate row(s).")
    return warnings


def _is_int(value: str) -> bool:
    try:
        int(value.replace(",", ""))
    except ValueError:
        return False
    return True


def _is_float(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def _is_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "false", "yes", "no"}


def _is_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True

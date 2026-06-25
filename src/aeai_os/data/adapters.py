from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from aeai_os.data.profiling import DataIngestionError, is_missing_value


class DatasetQueryAdapter(Protocol):
    """Read/query interface for local dataframe-like and future warehouse adapters."""

    def columns(self) -> list[str]: ...

    def preview(self, limit: int = 5) -> list[dict[str, str]]: ...

    def rows(self) -> list[dict[str, str]]: ...

    def aggregate_sum_by(self, group_column: str, value_column: str) -> dict[str, float]: ...


class CsvDatasetAdapter:
    def __init__(self, path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
        self._path = path
        self._rows = rows
        self._fieldnames = fieldnames

    @classmethod
    def from_path(cls, path: str | Path) -> CsvDatasetAdapter:
        csv_path = Path(path)
        if csv_path.suffix.lower() != ".csv":
            raise DataIngestionError(f"Unsupported dataset type for CSV adapter: {csv_path.suffix}")
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

        return cls(path=csv_path, rows=rows, fieldnames=fieldnames)

    def columns(self) -> list[str]:
        return list(self._fieldnames)

    def preview(self, limit: int = 5) -> list[dict[str, str]]:
        return [dict(row) for row in self._rows[: max(limit, 0)]]

    def rows(self) -> list[dict[str, str]]:
        return [dict(row) for row in self._rows]

    def aggregate_sum_by(self, group_column: str, value_column: str) -> dict[str, float]:
        self._assert_columns([group_column, value_column])
        totals: dict[str, float] = defaultdict(float)
        for row in self._rows:
            value = row[value_column]
            if is_missing_value(value):
                continue
            try:
                numeric_value = float(value.replace(",", ""))
            except ValueError:
                continue
            group = row[group_column] if not is_missing_value(row[group_column]) else "<missing>"
            totals[group] += numeric_value
        return dict(sorted(totals.items()))

    def _assert_columns(self, columns: Iterable[str]) -> None:
        missing = sorted(set(columns) - set(self._fieldnames))
        if missing:
            raise DataIngestionError(f"Unknown dataset columns: {', '.join(missing)}")

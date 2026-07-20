from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
from typing import Any

from aeai_os.data import DatasetQueryAdapter
from aeai_os.data.intelligence import DatasetAnalysisPlan
from aeai_os.data.profiling import is_missing_value, profile_tabular_rows


def analyze_generic_dataset(
    adapter: DatasetQueryAdapter,
    plan: DatasetAnalysisPlan,
) -> dict[str, Any]:
    rows = adapter.rows()
    columns = adapter.columns()
    profile = profile_tabular_rows("analysis-source", rows, columns)
    total_cells = len(rows) * len(columns)
    missing_cells = int(profile.quality_summary["missing_cells"])
    measures = [_measure_summary(name, rows) for name in plan.measures]
    dimensions = [_dimension_summary(name, rows) for name in plan.dimensions]
    trends = _time_series(rows, plan)
    outliers = _outliers(rows, plan.measures)
    completeness = 1 - (missing_cells / total_cells) if total_cells else 0.0
    insights = _insights(profile.row_count, measures, dimensions, trends, outliers, completeness)
    return {
        "analysis_type": "generic",
        "title": "Exploratory Dataset Analysis",
        "analysis_plan": plan.model_dump(),
        "dataset": {
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "columns": [
                {
                    "name": column.name,
                    "type": column.inferred_type,
                    "missing_count": column.missing_count,
                    "unique_count": column.unique_count,
                }
                for column in profile.columns
            ],
        },
        "kpis": {
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "completeness": round(completeness, 4),
            "duplicate_row_count": profile.quality_summary["duplicate_row_count"],
            "measure_count": len(plan.measures),
            "dimension_count": len(plan.dimensions),
            "time_column_count": len(plan.time_columns),
            "outlier_count": sum(item["outlier_count"] for item in outliers),
        },
        "measure_summaries": measures,
        "dimension_summaries": dimensions,
        "time_series": trends,
        "outliers": outliers,
        "insights": insights,
        "recommendations": _recommendations(plan, completeness, outliers),
        "limitations": [
            "Semantic roles are inferred from schema and values and should be reviewed.",
            "Associations and outliers are descriptive and do not establish causality.",
            "Forecasting is omitted unless a reliable time field and numeric measure are present.",
        ],
    }


def _measure_summary(column: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [value for row in rows if (value := _number(row.get(column))) is not None]
    return {
        "column": column,
        "count": len(values),
        "missing_count": len(rows) - len(values),
        "min": round(min(values), 4) if values else None,
        "max": round(max(values), 4) if values else None,
        "mean": round(mean(values), 4) if values else None,
        "median": round(median(values), 4) if values else None,
        "sum": round(sum(values), 4) if values else None,
    }


def _dimension_summary(column: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [str(row.get(column) or "<missing>") for row in rows]
    counts = Counter(values)
    return {
        "column": column,
        "unique_count": len(counts),
        "top_values": [
            {"value": value, "count": count, "share": round(count / len(values), 4)}
            for value, count in counts.most_common(10)
        ]
        if values
        else [],
    }


def _time_series(rows: list[dict[str, Any]], plan: DatasetAnalysisPlan) -> list[dict[str, Any]]:
    if not plan.time_columns:
        return []
    date_column = plan.time_columns[0]
    measure = plan.measures[0] if plan.measures else None
    buckets: dict[str, float] = defaultdict(float)
    for row in rows:
        month = _month(row.get(date_column))
        if month:
            value = _number(row.get(measure)) if measure else 1.0
            if value is not None:
                buckets[month] += value
    return [
        {"period": period, "value": round(value, 4), "measure": measure or "row_count"}
        for period, value in sorted(buckets.items())
    ]


def _outliers(rows: list[dict[str, Any]], measures: list[str]) -> list[dict[str, Any]]:
    results = []
    for column in measures[:10]:
        values = sorted(value for row in rows if (value := _number(row.get(column))) is not None)
        if len(values) < 4:
            results.append({"column": column, "outlier_count": 0, "lower": None, "upper": None})
            continue
        q1 = values[(len(values) - 1) // 4]
        q3 = values[((len(values) - 1) * 3) // 4]
        spread = q3 - q1
        lower, upper = q1 - 1.5 * spread, q3 + 1.5 * spread
        results.append(
            {
                "column": column,
                "outlier_count": sum(value < lower or value > upper for value in values),
                "lower": round(lower, 4),
                "upper": round(upper, 4),
            }
        )
    return results


def _insights(row_count, measures, dimensions, trends, outliers, completeness):
    insights = [f"Analyzed {row_count:,} rows with {completeness:.1%} populated cells."]
    if measures:
        strongest = max(measures, key=lambda item: abs(item.get("sum") or 0))
        insights.append(
            f"{strongest['column']} totals {strongest['sum']:,.2f} across "
            f"{strongest['count']:,} values."
        )
    if dimensions and dimensions[0]["top_values"]:
        top = dimensions[0]["top_values"][0]
        insights.append(
            f"{top['value']} is the largest {dimensions[0]['column']} segment at "
            f"{top['share']:.1%}."
        )
    if trends:
        insights.append(
            f"Time analysis produced {len(trends)} period(s) from the primary date field."
        )
    flagged = sum(item["outlier_count"] for item in outliers)
    insights.append(f"Robust range checks flagged {flagged} numeric value(s) for review.")
    return insights


def _recommendations(plan, completeness, outliers):
    recommendations = []
    if completeness < 0.95:
        recommendations.append(
            "Review missing values before operationalizing downstream decisions."
        )
    if sum(item["outlier_count"] for item in outliers):
        recommendations.append("Validate flagged numeric values against source-system records.")
    if plan.requires_clarification:
        recommendations.append("Provide business context before selecting decision-specific KPIs.")
    return recommendations or [
        "Review inferred semantic roles and select the next business question."
    ]


def _number(value: Any) -> float | None:
    if is_missing_value(value):
        return None
    text = str(value).strip()
    negative = text.startswith("(") and text.endswith(")")
    normalized = text.strip("()").replace(",", "")
    for symbol in ("$", "£", "€", "¥", "₹", "%"):
        normalized = normalized.replace(symbol, "")
    try:
        number = float(normalized)
    except ValueError:
        return None
    return -number if negative else number


def _month(value: Any) -> str | None:
    if is_missing_value(value):
        return None
    text = str(value).strip()
    for parser in (
        datetime.fromisoformat,
        lambda item: datetime.strptime(item, "%m/%d/%Y"),
        lambda item: datetime.strptime(item, "%d/%m/%Y"),
    ):
        try:
            parsed = parser(text)
            return parsed.strftime("%Y-%m")
        except ValueError:
            continue
    return None

# ruff: noqa: E501
from __future__ import annotations

from html import escape
from typing import Any

from aeai_os.visualization.dashboard import ProcurementChartSpec


def build_generic_chart_specs(analysis: dict[str, Any]) -> list[ProcurementChartSpec]:
    kpis = analysis["kpis"]
    plan = analysis["analysis_plan"]
    measures = analysis.get("measure_summaries", [])
    dimensions = analysis.get("dimension_summaries", [])
    trends = analysis.get("time_series", [])
    outliers = analysis.get("outliers", [])
    specs = [
        ProcurementChartSpec(
            slug="dataset-overview",
            title="Dataset Overview",
            chart_type="metric_grid",
            description="Size, completeness, semantic roles, and duplicate records.",
            data=[{"metric": key, "value": value} for key, value in kpis.items()],
            body_html=_metric_grid(kpis),
        ),
        ProcurementChartSpec(
            slug="semantic-roles",
            title="Semantic Column Map",
            chart_type="table",
            description="Inferred measures, dimensions, dates, and identifiers.",
            data=[{"role": key, "columns": value} for key, value in _roles(plan).items()],
            body_html=_roles_table(plan),
        ),
        ProcurementChartSpec(
            slug="measure-summary",
            title="Numeric Measure Summary",
            chart_type="table",
            description="Descriptive statistics for inferred numeric measures.",
            data=measures,
            body_html=_measure_table(measures),
        ),
        ProcurementChartSpec(
            slug="segment-profile",
            title="Leading Segment Distribution",
            chart_type="bar",
            description="Top values for the primary inferred dimension.",
            data=dimensions[0]["top_values"] if dimensions else [],
            body_html=_segment_bars(dimensions),
        ),
        ProcurementChartSpec(
            slug="outlier-review",
            title="Numeric Outlier Review",
            chart_type="table",
            description="Robust IQR range checks by numeric measure.",
            data=outliers,
            body_html=_outlier_table(outliers),
        ),
    ]
    if trends:
        specs.append(
            ProcurementChartSpec(
                slug="time-trend",
                title="Primary Time Trend",
                chart_type="line",
                description="Monthly aggregation of the primary measure or record count.",
                data=trends,
                body_html=_trend_bars(trends),
            )
        )
    return specs


def render_generic_dashboard_document(
    analysis: dict[str, Any],
    charts: list[ProcurementChartSpec],
    source_artifact_id: str,
    chart_artifact_ids: list[str],
) -> str:
    from aeai_os.visualization.premium import render_premium_dashboard_document

    return render_premium_dashboard_document(
        analysis, charts, source_artifact_id, chart_artifact_ids
    )


def _roles(plan):
    return {
        "Measures": plan["measures"],
        "Dimensions": plan["dimensions"],
        "Time": plan["time_columns"],
        "Identifiers": plan["identifiers"],
    }


def _metric_grid(kpis):
    return (
        '<div class="metrics">'
        + "".join(
            f'<div class="metric"><span>{escape(key.replace("_", " ").title())}</span><strong>{escape(_format(value))}</strong></div>'
            for key, value in kpis.items()
        )
        + "</div>"
    )


def _roles_table(plan):
    return _table(
        ["Role", "Detected columns"],
        [[role, ", ".join(columns) or "None"] for role, columns in _roles(plan).items()],
    )


def _measure_table(items):
    return _table(
        ["Measure", "Count", "Mean", "Median", "Min", "Max"],
        [
            [item["column"], item["count"], item["mean"], item["median"], item["min"], item["max"]]
            for item in items
        ],
    )


def _segment_bars(dimensions):
    if not dimensions or not dimensions[0]["top_values"]:
        return "<p>No categorical dimension was suitable for segmentation.</p>"
    items = dimensions[0]["top_values"]
    maximum = max(item["count"] for item in items) or 1
    return (
        '<div class="bars">'
        + "".join(
            f'<div class="bar"><span>{escape(str(item["value"]))}</span><div class="track"><div class="fill" style="width:{item["count"] / maximum:.0%}"></div></div><strong>{item["count"]}</strong></div>'
            for item in items
        )
        + "</div>"
    )


def _outlier_table(items):
    return _table(
        ["Measure", "Flagged", "Lower", "Upper"],
        [[item["column"], item["outlier_count"], item["lower"], item["upper"]] for item in items],
    )


def _trend_bars(items):
    maximum = max(abs(item["value"]) for item in items) or 1
    return (
        '<div class="bars">'
        + "".join(
            f'<div class="bar"><span>{escape(item["period"])}</span><div class="track"><div class="fill" style="width:{abs(item["value"]) / maximum:.0%}"></div></div><strong>{escape(_format(item["value"]))}</strong></div>'
            for item in items
        )
        + "</div>"
    )


def _table(headers, rows):
    if not rows:
        return "<p>No applicable values were detected.</p>"
    head = "".join(f"<th>{escape(str(value))}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(_format(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _format(value):
    if value is None:
        return "Not available"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)

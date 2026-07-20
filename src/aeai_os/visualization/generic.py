# ruff: noqa: E501
from __future__ import annotations

import json
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
    kpis = analysis["kpis"]
    plan = analysis["analysis_plan"]
    sections = "".join(
        f'<section class="panel"><div class="panel-head"><div><span>{escape(chart.chart_type)}</span>'
        f"<h2>{escape(chart.title)}</h2><p>{escape(chart.description)}</p></div></div>"
        f"{chart.body_html}</section>"
        for chart in charts
    )
    links = "".join(
        f"<li><code>{escape(artifact_id)}</code></li>" for artifact_id in chart_artifact_ids
    )
    payload = json.dumps({"analysis": analysis, "chart_artifact_ids": chart_artifact_ids}).replace(
        "<", "\\u003c"
    )
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dataset Intelligence Dashboard</title><style>
:root{{--bg:#f3f5f8;--surface:#fff;--ink:#17191f;--muted:#68707d;--line:#dfe3e9;--blue:#315be8;--green:#087a55;--amber:#9a5b13}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;letter-spacing:0}}main{{width:min(1240px,calc(100% - 32px));margin:auto;padding:38px 0 60px}}header{{display:flex;justify-content:space-between;gap:24px;padding-bottom:24px;border-bottom:1px solid var(--line)}}.eyebrow,.panel-head span{{color:var(--blue);font-size:.74rem;font-weight:800;text-transform:uppercase}}h1{{margin:6px 0;font-size:2.25rem}}h2{{margin:4px 0;font-size:1.05rem}}p{{color:var(--muted)}}.recipe{{align-self:start;padding:8px 10px;border:1px solid #bfc9f8;background:#eef1ff;border-radius:6px;font-weight:750}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);margin:20px 0;border:1px solid var(--line);background:var(--surface)}}.summary div{{padding:16px;border-right:1px solid var(--line)}}.summary span,.summary strong{{display:block}}.summary span{{color:var(--muted);font-size:.76rem}}.summary strong{{margin-top:4px;font-size:1.35rem}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.panel{{padding:20px;border:1px solid var(--line);background:var(--surface)}}.panel p{{margin:4px 0 14px;font-size:.85rem}}table{{width:100%;border-collapse:collapse;font-size:.82rem}}th,td{{padding:8px;border-bottom:1px solid var(--line);text-align:left;overflow-wrap:anywhere}}th{{color:var(--muted);font-size:.7rem;text-transform:uppercase}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}}.metric{{padding:10px;background:#f7f8fa}}.metric strong,.metric span{{display:block}}.metric span{{color:var(--muted);font-size:.72rem}}.bars{{display:grid;gap:8px}}.bar{{display:grid;grid-template-columns:minmax(90px,1fr) 2fr 58px;gap:8px;align-items:center;font-size:.8rem}}.track{{height:8px;background:#e8ebf0}}.fill{{height:100%;background:var(--green)}}code{{font-size:.72rem}}@media(max-width:760px){{header{{display:block}}.summary,.grid{{grid-template-columns:1fr 1fr}}.summary div{{border-bottom:1px solid var(--line)}}.grid{{grid-template-columns:1fr}}.metrics{{grid-template-columns:1fr 1fr}}}}@media(max-width:430px){{main{{width:calc(100% - 20px);padding-top:24px}}.summary{{grid-template-columns:1fr 1fr}}h1{{font-size:1.75rem}}}}
</style></head><body><main data-source-artifact-id="{escape(source_artifact_id)}"><header><div><span class="eyebrow">Dynamic dataset intelligence</span><h1>{escape(analysis["title"])}</h1><p>Schema-aware analysis of {kpis["row_count"]:,} records with visible inference and limitations.</p></div><div class="recipe">{escape(plan["recipe"].title())} · {plan["confidence"]:.0%} confidence</div></header><section class="summary"><div><span>Rows</span><strong>{kpis["row_count"]:,}</strong></div><div><span>Columns</span><strong>{kpis["column_count"]}</strong></div><div><span>Completeness</span><strong>{kpis["completeness"]:.1%}</strong></div><div><span>Flagged values</span><strong>{kpis["outlier_count"]}</strong></div></section><div class="grid">{sections}</div><section hidden><ul>{links}</ul></section></main><script type="application/json" data-role="dashboard-data">{payload}</script></body></html>'''


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

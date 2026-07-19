from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from typing import Any


class VisualizationError(ValueError):
    pass


@dataclass(frozen=True)
class ProcurementChartSpec:
    slug: str
    title: str
    chart_type: str
    description: str
    data: list[dict[str, Any]]
    body_html: str


def build_procurement_chart_specs(analysis: dict[str, Any]) -> list[ProcurementChartSpec]:
    _validate_analysis_payload(analysis)
    kpis = analysis["kpis"]
    supplier_spend = list(analysis["spend_by_supplier"])
    category_spend = list(analysis["spend_by_category"])
    trend = list(analysis["spend_trend"])
    outliers = list(analysis["outliers"])
    anomalies = list(analysis.get("anomalies", outliers))
    currency_symbol = analysis.get("dataset", {}).get("currency_symbol", "$")

    return [
        ProcurementChartSpec(
            slug="kpi-summary",
            title="Key Procurement KPIs",
            chart_type="metric_grid",
            description="Executive summary of spend, suppliers, categories, outliers, and savings.",
            data=[
                {"metric": "Total spend", "value": kpis["total_spend"]},
                {"metric": "Suppliers", "value": kpis["supplier_count"]},
                {"metric": "Categories", "value": kpis["category_count"]},
                {"metric": "Outliers", "value": kpis["outlier_count"]},
                {
                    "metric": "Flagged transactions",
                    "value": kpis.get("anomaly_count", len(anomalies)),
                },
                {"metric": "High risk", "value": kpis.get("high_risk_count", 0)},
                {"metric": "Estimated savings", "value": kpis["estimated_savings"]},
            ],
            body_html=_metric_grid(kpis, currency_symbol),
        ),
        ProcurementChartSpec(
            slug="supplier-spend",
            title="Supplier Spend Concentration",
            chart_type="bar",
            description="Ranked supplier spend with share of total spend.",
            data=supplier_spend,
            body_html=_bar_chart(
                rows=supplier_spend,
                label_key="supplier",
                value_key="spend",
                share_key="share",
                color="#2563eb",
                currency_symbol=currency_symbol,
            ),
        ),
        ProcurementChartSpec(
            slug="category-breakdown",
            title="Category Spend Breakdown",
            chart_type="bar",
            description="Spend grouped by procurement category.",
            data=category_spend,
            body_html=_bar_chart(
                rows=category_spend,
                label_key="category",
                value_key="spend",
                share_key="share",
                color="#0f766e",
                currency_symbol=currency_symbol,
            ),
        ),
        ProcurementChartSpec(
            slug="monthly-trend",
            title="Monthly Spend Trend",
            chart_type="line",
            description="Month-over-month procurement spend trend.",
            data=trend,
            body_html=_line_chart(
                rows=trend,
                label_key="month",
                value_key="spend",
                currency_symbol=currency_symbol,
            ),
        ),
        ProcurementChartSpec(
            slug="anomaly-review",
            title="Anomaly Investigation",
            chart_type="table",
            description="Ranked, explainable procurement risks ready for investigator review.",
            data=anomalies,
            body_html=_anomaly_table(anomalies, currency_symbol),
        ),
    ]


def render_chart_document(chart: ProcurementChartSpec, source_artifact_id: str) -> str:
    return _document_shell(
        title=chart.title,
        body=f"""
        <main class="chart-page" data-source-artifact-id="{escape(source_artifact_id)}">
          <header>
            <p class="eyebrow">Procurement dashboard chart</p>
            <h1>{escape(chart.title)}</h1>
            <p>{escape(chart.description)}</p>
          </header>
          <section class="chart-panel">
            {chart.body_html}
          </section>
          <script type="application/json" data-role="chart-data">
            {_json_script({"source_artifact_id": source_artifact_id, "data": chart.data})}
          </script>
        </main>
        """,
    )


def render_dashboard_document(
    analysis: dict[str, Any],
    charts: list[ProcurementChartSpec],
    source_artifact_id: str,
    chart_artifact_ids: list[str] | None = None,
) -> str:
    _validate_analysis_payload(analysis)
    chart_ids = list(chart_artifact_ids or [])
    chart_sections = "\n".join(
        f"""
        <section class="dashboard-chart" data-chart-type="{escape(chart.chart_type)}">
          <div class="chart-heading">
            <h2>{escape(chart.title)}</h2>
            <p>{escape(chart.description)}</p>
          </div>
          {chart.body_html}
        </section>
        """
        for chart in charts
    )
    insights = "\n".join(
        f"<li>{escape(str(insight))}</li>" for insight in analysis.get("insights", [])
    )
    source_payload = {
        "source_artifact_id": source_artifact_id,
        "chart_artifact_ids": chart_ids,
        "analysis": analysis,
    }
    kpis = analysis["kpis"]
    row_count = analysis.get("dataset", {}).get("row_count", 0)
    currency_symbol = analysis.get("dataset", {}).get("currency_symbol", "$")
    anomaly_count = kpis.get("anomaly_count", len(analysis.get("anomalies", [])))

    return _document_shell(
        title="Procurement Dashboard",
        body=f"""
        <main class="dashboard" data-source-artifact-id="{escape(source_artifact_id)}">
          <header class="dashboard-hero">
            <p class="eyebrow">Executive procurement intelligence</p>
            <h1>Procurement Dashboard</h1>
            <p>
              Decision-ready analysis of {escape(str(row_count))} procurement transactions with
              traceable metrics, anomalies, and savings opportunities.
            </p>
          </header>

          <section class="dashboard-kpis">
            <div>
              <span>Total spend</span>
              <strong>{escape(_money(kpis["total_spend"], currency_symbol))}</strong>
            </div>
            <div>
              <span>Suppliers</span>
              <strong>{escape(str(kpis["supplier_count"]))}</strong>
            </div>
            <div>
              <span>Categories</span>
              <strong>{escape(str(kpis["category_count"]))}</strong>
            </div>
            <div>
              <span>Estimated savings</span>
              <strong>{escape(_money(kpis["estimated_savings"], currency_symbol))}</strong>
            </div>
            <div>
              <span>Flagged transactions</span>
              <strong>{escape(str(anomaly_count))}</strong>
            </div>
            <div>
              <span>Risk exposure</span>
              <strong>{escape(_money(kpis.get("risk_exposure", 0), currency_symbol))}</strong>
            </div>
          </section>

          <section class="insights">
            <h2>Executive Insights</h2>
            <ul>{insights}</ul>
          </section>

          <section class="chart-grid">
            {chart_sections}
          </section>

          <script type="application/json" data-role="dashboard-data">
            {_json_script(source_payload)}
          </script>
        </main>
        """,
    )


def _validate_analysis_payload(analysis: dict[str, Any]) -> None:
    required = {
        "kpis",
        "spend_by_supplier",
        "spend_by_category",
        "spend_trend",
        "outliers",
    }
    missing = sorted(required - set(analysis))
    if missing:
        raise VisualizationError(
            "Analysis payload is missing required sections: " + ", ".join(missing)
        )

    kpi_keys = {
        "total_spend",
        "supplier_count",
        "category_count",
        "outlier_count",
        "estimated_savings",
    }
    missing_kpis = sorted(kpi_keys - set(analysis["kpis"]))
    if missing_kpis:
        raise VisualizationError("Analysis KPI payload is missing: " + ", ".join(missing_kpis))


def _metric_grid(kpis: dict[str, Any], currency_symbol: str = "$") -> str:
    metrics = [
        ("Total spend", _money(kpis["total_spend"], currency_symbol)),
        ("Suppliers", str(kpis["supplier_count"])),
        ("Categories", str(kpis["category_count"])),
        ("Outliers", str(kpis["outlier_count"])),
        ("Flagged transactions", str(kpis.get("anomaly_count", kpis["outlier_count"]))),
        ("High risk", str(kpis.get("high_risk_count", 0))),
        ("Estimated savings", _money(kpis["estimated_savings"], currency_symbol)),
    ]
    items = "\n".join(
        f"""
        <div class="metric-card">
          <span>{escape(label)}</span>
          <strong>{escape(value)}</strong>
        </div>
        """
        for label, value in metrics
    )
    return f'<div class="metric-grid">{items}</div>'


def _bar_chart(
    rows: list[dict[str, Any]],
    label_key: str,
    value_key: str,
    share_key: str,
    color: str,
    currency_symbol: str = "$",
) -> str:
    if not rows:
        return '<p class="empty-state">No spend data was available for this view.</p>'

    top_rows = rows[:8]
    max_value = max(_number(row[value_key]) for row in top_rows) or 1.0
    height = 72 + len(top_rows) * 44
    bars: list[str] = []
    for index, row in enumerate(top_rows):
        y = 40 + index * 44
        value = _number(row[value_key])
        width = max(4.0, (value / max_value) * 560)
        label = _truncate(str(row[label_key]), 26)
        share = _percent(_number(row.get(share_key, 0)))
        bars.append(
            f"""
            <g>
              <text x="0" y="{y + 16}" class="axis-label">{escape(label)}</text>
              <rect x="180" y="{y}" width="{width:.2f}" height="22" rx="4" fill="{color}" />
              <text x="{190 + width:.2f}" y="{y + 16}" class="value-label">
                {escape(_money(value, currency_symbol))} ({escape(share)})
              </text>
            </g>
            """
        )

    return f"""
    <svg class="chart-svg" viewBox="0 0 920 {height}" role="img">
      <line x1="180" y1="28" x2="180" y2="{height - 20}" class="grid-line" />
      {"".join(bars)}
    </svg>
    """


def _line_chart(
    rows: list[dict[str, Any]],
    label_key: str,
    value_key: str,
    currency_symbol: str = "$",
) -> str:
    if not rows:
        return '<p class="empty-state">No monthly trend data was available.</p>'

    width = 920
    height = 330
    left = 64
    right = 32
    top = 36
    bottom = 58
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [_number(row[value_key]) for row in rows]
    max_value = max(values) or 1.0
    x_step = plot_width / max(len(rows) - 1, 1)

    points: list[tuple[float, float]] = []
    labels: list[str] = []
    for index, row in enumerate(rows):
        x = left + index * x_step
        y = top + plot_height - (_number(row[value_key]) / max_value) * plot_height
        points.append((x, y))
        labels.append(str(row[label_key]))

    point_string = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    markers = "\n".join(
        f"""
        <g>
          <circle cx="{x:.2f}" cy="{y:.2f}" r="5" fill="#2563eb" />
          <text x="{x:.2f}" y="{height - 24}" text-anchor="middle" class="axis-label">
            {escape(_truncate(labels[index], 12))}
          </text>
          <text x="{x:.2f}" y="{y - 12:.2f}" text-anchor="middle" class="value-label">
            {escape(_compact_money(values[index], currency_symbol))}
          </text>
        </g>
        """
        for index, (x, y) in enumerate(points)
    )

    return f"""
    <svg class="chart-svg" viewBox="0 0 {width} {height}" role="img">
      <line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" class="grid-line" />
      <line
        x1="{left}"
        y1="{height - bottom}"
        x2="{width - right}"
        y2="{height - bottom}"
        class="grid-line"
      />
      <polyline points="{point_string}" fill="none" stroke="#2563eb" stroke-width="4" />
      {markers}
    </svg>
    """


def _anomaly_table(anomalies: list[dict[str, Any]], currency_symbol: str = "$") -> str:
    if not anomalies:
        return '<p class="empty-state">No transactions crossed the anomaly review threshold.</p>'

    rows = "\n".join(
        f"""
        <tr data-anomaly-row data-severity="{escape(str(item.get("severity", "medium")))}"
            data-search="{escape(_anomaly_search_text(item))}">
          <td>{escape(str(item.get("row_number", "")))}</td>
          <td>
            <strong>{escape(str(item.get("supplier", "")))}</strong>
            <span class="cell-detail">{escape(str(item.get("category", "")))}</span>
          </td>
          <td>{escape(_money(item.get("amount", 0), currency_symbol))}</td>
          <td>
            <div class="risk-score">
              <strong>{escape(str(item.get("risk_score", "--")))}</strong><span>/100</span>
            </div>
            <span class="severity severity-{escape(str(item.get("severity", "medium")))}">
              {escape(str(item.get("severity", "medium")).title())}
            </span>
          </td>
          <td>{escape(_percent(_number(item.get("confidence", 0))))}</td>
          <td>
            <strong>{escape(str(item.get("reason", "Review required")))}</strong>
            <ul class="signal-list">{_signal_items(item)}</ul>
          </td>
          <td>{escape(str(item.get("recommended_action", "Review transaction.")))}</td>
        </tr>
        """
        for item in anomalies[:50]
    )
    return f"""
    <div class="anomaly-queue" data-anomaly-queue>
      <div class="anomaly-toolbar">
        <div class="severity-filter" role="group" aria-label="Filter anomaly severity">
          <button type="button" class="active" data-severity-filter="all">All</button>
          <button type="button" data-severity-filter="priority">Critical &amp; High</button>
          <button type="button" data-severity-filter="medium">Medium</button>
        </div>
        <label class="anomaly-search">
          <span>Search transactions</span>
          <input type="search" placeholder="Supplier, category, signal" data-anomaly-search />
        </label>
      </div>
      <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Row</th>
            <th>Transaction</th>
            <th>Amount</th>
            <th>Risk</th>
            <th>Confidence</th>
            <th>Evidence</th>
            <th>Recommended action</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      </div>
      <p class="queue-count" data-anomaly-count></p>
    </div>
    {_anomaly_script()}
    """


def _signal_items(item: dict[str, Any]) -> str:
    return "".join(
        f'<li><span>+{escape(str(signal.get("weight", 0)))}</span>'
        f'{escape(str(signal.get("evidence", signal.get("label", ""))))}</li>'
        for signal in item.get("signals", [])
    )


def _anomaly_search_text(item: dict[str, Any]) -> str:
    values = [item.get("supplier"), item.get("category"), item.get("reason")]
    values.extend(signal.get("evidence") for signal in item.get("signals", []))
    return " ".join(str(value or "") for value in values).lower()


def _anomaly_script() -> str:
    return """
    <script>
      document.querySelectorAll('[data-anomaly-queue]').forEach((queue) => {
        const rows = [...queue.querySelectorAll('[data-anomaly-row]')];
        const search = queue.querySelector('[data-anomaly-search]');
        const count = queue.querySelector('[data-anomaly-count]');
        let severity = 'all';
        const update = () => {
          const query = search.value.trim().toLowerCase();
          let visible = 0;
          rows.forEach((row) => {
            const matchesSeverity = severity === 'all'
              || (severity === 'priority' && ['critical', 'high'].includes(row.dataset.severity))
              || row.dataset.severity === severity;
            const matchesSearch = !query || row.dataset.search.includes(query);
            row.hidden = !(matchesSeverity && matchesSearch);
            if (!row.hidden) visible += 1;
          });
          count.textContent = `${visible} of ${rows.length} flagged transactions shown`;
        };
        queue.querySelectorAll('[data-severity-filter]').forEach((button) => {
          button.addEventListener('click', () => {
            severity = button.dataset.severityFilter;
            queue.querySelectorAll('[data-severity-filter]').forEach((item) => {
              item.classList.toggle('active', item === button);
            });
            update();
          });
        });
        search.addEventListener('input', update);
        update();
      });
    </script>
    """


def _document_shell(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --background: #f7f8fb;
      --surface: #ffffff;
      --surface-strong: #eef2f7;
      --text: #172033;
      --muted: #64748b;
      --border: #d8dee9;
      --accent: #2563eb;
      --accent-2: #0f766e;
      --danger: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--background);
      color: var(--text);
      font-family:
        Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    main {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 32px 0 44px;
    }}
    h1, h2, p {{ margin-top: 0; }}
    code {{
      padding: 2px 6px;
      border-radius: 5px;
      background: var(--surface-strong);
      font-size: 0.9em;
    }}
    .eyebrow {{
      margin-bottom: 8px;
      color: var(--accent-2);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .dashboard-hero, .chart-page header {{
      padding: 8px 0 22px;
    }}
    .dashboard-hero h1, .chart-page h1 {{
      margin-bottom: 8px;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1.05;
    }}
    .dashboard-hero p, .chart-page header p {{
      max-width: 760px;
      color: var(--muted);
    }}
    .dashboard-kpis, .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 10px 0 22px;
    }}
    .dashboard-kpis div, .metric-card, .dashboard-chart, .insights, .chart-panel {{
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: 0 10px 30px rgb(15 23 42 / 8%);
    }}
    .dashboard-kpis div, .metric-card {{
      padding: 16px;
    }}
    .dashboard-kpis span, .metric-card span {{
      display: block;
      color: var(--muted);
      font-size: 0.84rem;
      font-weight: 700;
    }}
    .dashboard-kpis strong, .metric-card strong {{
      display: block;
      margin-top: 6px;
      font-size: clamp(1.2rem, 2vw, 1.8rem);
      line-height: 1.1;
    }}
    .insights {{
      margin-bottom: 20px;
      padding: 20px;
    }}
    .insights h2, .chart-heading h2 {{
      margin-bottom: 6px;
      font-size: 1.15rem;
    }}
    .insights ul {{
      margin: 0;
      padding-left: 20px;
      color: var(--muted);
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .dashboard-chart, .chart-panel {{
      overflow: hidden;
      padding: 18px;
    }}
    .dashboard-chart[data-chart-type="table"] {{
      grid-column: 1 / -1;
    }}
    .chart-heading p {{
      margin-bottom: 16px;
      color: var(--muted);
    }}
    .chart-svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .axis-label {{
      fill: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }}
    .value-label {{
      fill: var(--text);
      font-size: 13px;
      font-weight: 700;
    }}
    .grid-line {{
      stroke: var(--border);
      stroke-width: 1;
    }}
    .table-wrap {{
      overflow-x: auto;
    }}
    .anomaly-toolbar {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 16px;
    }}
    .severity-filter {{
      display: inline-flex;
      padding: 3px;
      border: 1px solid var(--border);
      border-radius: 7px;
      background: var(--surface-strong);
    }}
    .severity-filter button {{
      min-height: 34px;
      padding: 6px 11px;
      border: 0;
      border-radius: 5px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
      font: inherit;
      font-size: 0.82rem;
      font-weight: 700;
    }}
    .severity-filter button.active {{
      color: var(--text);
      background: var(--surface);
      box-shadow: 0 1px 3px rgb(15 23 42 / 12%);
    }}
    .anomaly-search {{
      min-width: min(300px, 100%);
    }}
    .anomaly-search span {{
      display: block;
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 0.75rem;
      font-weight: 700;
    }}
    .anomaly-search input {{
      width: 100%;
      min-height: 40px;
      padding: 8px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text);
      background: var(--surface);
      font: inherit;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: var(--surface-strong);
      color: var(--muted);
      font-size: 0.78rem;
      text-transform: uppercase;
    }}
    .cell-detail {{
      display: block;
      margin-top: 3px;
      color: var(--muted);
      font-size: 0.8rem;
    }}
    .risk-score {{
      display: flex;
      align-items: baseline;
      gap: 2px;
      margin-bottom: 5px;
    }}
    .risk-score strong {{ font-size: 1.2rem; }}
    .risk-score span {{ color: var(--muted); font-size: 0.72rem; }}
    .severity {{
      display: inline-flex;
      padding: 3px 7px;
      border-radius: 5px;
      font-size: 0.72rem;
      font-weight: 800;
    }}
    .severity-critical {{ color: #7a271a; background: #fee4e2; }}
    .severity-high {{ color: #912018; background: #ffead5; }}
    .severity-medium {{ color: #854a0e; background: #fef0c7; }}
    .severity-low {{ color: #175cd3; background: #dbeafe; }}
    .signal-list {{
      display: grid;
      gap: 5px;
      margin: 8px 0 0;
      padding: 0;
      color: var(--muted);
      font-size: 0.78rem;
      list-style: none;
    }}
    .signal-list span {{
      display: inline-block;
      min-width: 28px;
      margin-right: 5px;
      color: var(--danger);
      font-weight: 800;
    }}
    .queue-count {{
      margin: 12px 0 0;
      color: var(--muted);
      font-size: 0.82rem;
    }}
    tr[hidden] {{ display: none; }}
    .empty-state {{
      margin: 0;
      padding: 18px;
      border: 1px dashed var(--border);
      border-radius: 8px;
      color: var(--muted);
      background: #fbfcfe;
    }}
    @media (max-width: 700px) {{
      main {{
        width: min(100vw - 20px, 1180px);
        padding-top: 20px;
      }}
      .chart-grid {{
        grid-template-columns: 1fr;
      }}
      .dashboard-chart, .chart-panel {{
        padding: 14px;
      }}
      .anomaly-toolbar {{ align-items: stretch; flex-direction: column; }}
      .severity-filter {{ overflow-x: auto; }}
    }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _json_script(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True).replace("<", "\\u003c")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any, currency_symbol: str = "$") -> str:
    return f"{currency_symbol}{_number(value):,.2f}"


def _compact_money(value: Any, currency_symbol: str = "$") -> str:
    amount = _number(value)
    if abs(amount) >= 1_000_000:
        return f"{currency_symbol}{amount / 1_000_000:.1f}M"
    if abs(amount) >= 1_000:
        return f"{currency_symbol}{amount / 1_000:.1f}K"
    return f"{currency_symbol}{amount:.0f}"


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."

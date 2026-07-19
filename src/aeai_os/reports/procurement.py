from __future__ import annotations

from typing import Any

from aeai_os.runs.models import ArtifactRecord
from aeai_os.schemas.enums import ArtifactType


def render_procurement_markdown_report(
    analysis: dict[str, Any],
    artifacts: list[ArtifactRecord],
    schema_profile: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> str:
    kpis = analysis["kpis"]
    insights = analysis.get("insights", [])
    savings_opportunities = analysis.get("savings_opportunities", [])
    missing_risks = analysis.get("missing_data_risks", [])
    charts = [artifact for artifact in artifacts if artifact.type == ArtifactType.CHART]
    dashboards = [artifact for artifact in artifacts if artifact.type == ArtifactType.DASHBOARD]
    currency_symbol = analysis.get("dataset", {}).get("currency_symbol", "$")

    sections = [
        "# Procurement Analysis Report",
        "## Executive Summary",
        _executive_summary(kpis, insights, currency_symbol),
        "## Key Findings",
        _bullet_list(insights),
        "## Procurement KPIs",
        _kpi_table(kpis, currency_symbol),
        "## Dataset Quality",
        _quality_section(schema_profile=schema_profile, quality_report=quality_report),
        "## Charts And Dashboard",
        _chart_section(charts=charts, dashboards=dashboards),
        "## Recommendations",
        _recommendations_section(
            savings_opportunities=savings_opportunities,
            currency_symbol=currency_symbol,
        ),
        "## Missing Data Risks",
        _missing_risks_section(missing_risks=missing_risks),
        "## Artifact Lineage",
        _artifact_lineage_section(artifacts),
        "## Assumptions",
        _bullet_list(
            [
                (
                    "The input dataset uses procurement-style supplier, category, amount, "
                    "and date fields."
                ),
                "Spend amounts are normalized to a single reporting currency before analysis.",
                "The generated report summarizes deterministic artifacts produced within this run.",
            ]
        ),
        "## Limitations",
        _bullet_list(
            [
                (
                    "Outlier detection uses a simple IQR rule and should be reviewed before "
                    "audit action."
                ),
                "Savings estimates are directional opportunities, not negotiated outcomes.",
                (
                    "The MVP report references local chart artifacts instead of embedding "
                    "binary PDF charts."
                ),
            ]
        ),
    ]
    return "\n\n".join(sections) + "\n"


def _executive_summary(
    kpis: dict[str, Any], insights: list[str], currency_symbol: str = "$"
) -> str:
    first_insight = insights[0] if insights else "No insight narrative was generated."
    total_spend = _money(kpis["total_spend"], currency_symbol)
    return (
        f"The workflow analyzed {total_spend} in procurement spend "
        f"across {kpis['supplier_count']} supplier(s) and {kpis['category_count']} "
        f"category group(s). {first_insight}"
    )


def _kpi_table(kpis: dict[str, Any], currency_symbol: str = "$") -> str:
    rows = [
        ("Total spend", _money(kpis["total_spend"], currency_symbol)),
        ("Supplier count", str(kpis["supplier_count"])),
        ("Category count", str(kpis["category_count"])),
        (
            "Average transaction value",
            _money(kpis.get("average_transaction_value", 0), currency_symbol),
        ),
        ("Outlier count", str(kpis["outlier_count"])),
        ("Estimated savings", _money(kpis["estimated_savings"], currency_symbol)),
    ]
    return _markdown_table(["Metric", "Value"], rows)


def _quality_section(
    schema_profile: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
) -> str:
    rows = []
    if schema_profile:
        rows.extend(
            [
                ("Rows", str(schema_profile.get("row_count", "unknown"))),
                ("Columns", str(schema_profile.get("column_count", "unknown"))),
            ]
        )
    if quality_report:
        rows.extend(
            [
                ("Missing cells", str(quality_report.get("missing_cells", "unknown"))),
                (
                    "Duplicate rows",
                    str(quality_report.get("duplicate_row_count", "unknown")),
                ),
            ]
        )
    if not rows:
        return "No schema or quality artifact was available for this report."
    return _markdown_table(["Quality Signal", "Value"], rows)


def _chart_section(
    charts: list[ArtifactRecord],
    dashboards: list[ArtifactRecord],
) -> str:
    rows: list[tuple[str, str, str]] = []
    for artifact in charts:
        rows.append(
            (
                artifact.metadata.get("title", artifact.id),
                artifact.id,
                artifact.uri,
            )
        )
    for artifact in dashboards:
        rows.append(
            (
                artifact.metadata.get("title", "Procurement Dashboard"),
                artifact.id,
                artifact.uri,
            )
        )
    if not rows:
        return "No chart or dashboard artifacts were available for this report."
    return _markdown_table(["Artifact", "ID", "URI"], rows)


def _recommendations_section(
    savings_opportunities: list[dict[str, Any]], currency_symbol: str = "$"
) -> str:
    if not savings_opportunities:
        return "No savings opportunities were identified."
    recommendations = []
    for item in savings_opportunities:
        kind = str(item.get("type", "opportunity")).replace("_", " ")
        savings = _money(item.get("estimated_savings", 0), currency_symbol)
        rationale = item.get("rationale", "Review this procurement opportunity.")
        recommendations.append(f"{kind.title()}: {rationale} Estimated savings: {savings}.")
    return _bullet_list(recommendations)


def _missing_risks_section(missing_risks: list[dict[str, Any]]) -> str:
    if not missing_risks:
        return "No missing-data risks were identified."
    rows = [
        (
            item.get("field_role", ""),
            item.get("column") or "<unresolved>",
            str(item.get("missing_count", 0)),
            str(item.get("severity", "unknown")),
        )
        for item in missing_risks
    ]
    return _markdown_table(["Field Role", "Column", "Missing Count", "Severity"], rows)


def _artifact_lineage_section(artifacts: list[ArtifactRecord]) -> str:
    rows = [
        (
            artifact.id,
            artifact.type.value,
            artifact.producer_node_id or "<external>",
            ", ".join(artifact.source_artifact_ids) or "<none>",
        )
        for artifact in artifacts
    ]
    return _markdown_table(["ID", "Type", "Producer", "Sources"], rows)


def _markdown_table(headers: list[str], rows: list[tuple[Any, ...]]) -> str:
    header = "| " + " | ".join(_cell(value) for value in headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def _bullet_list(items: list[str]) -> str:
    if not items:
        return "- No items were generated."
    return "\n".join(f"- {item}" for item in items)


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any, currency_symbol: str = "$") -> str:
    return f"{currency_symbol}{_number(value):,.2f}"

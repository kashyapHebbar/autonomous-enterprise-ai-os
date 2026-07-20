from __future__ import annotations

from typing import Any

from aeai_os.runs.models import ArtifactRecord
from aeai_os.schemas.enums import ArtifactType


def render_generic_markdown_report(
    analysis: dict[str, Any],
    artifacts: list[ArtifactRecord],
    schema_profile: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> str:
    kpis = analysis["kpis"]
    plan = analysis["analysis_plan"]
    charts = [artifact for artifact in artifacts if artifact.type == ArtifactType.CHART]
    lines = [
        "# Exploratory Dataset Analysis Report",
        "",
        "## Executive Summary",
        "",
        (
            f"The workflow analyzed {kpis['row_count']:,} rows across "
            f"{kpis['column_count']} columns using the `{plan['recipe']}` recipe "
            f"at {plan['confidence']:.0%} inference confidence."
        ),
        "",
        "## Inferred Analysis Plan",
        "",
        _table(
            ["Role", "Columns"],
            [
                ("Measures", ", ".join(plan["measures"]) or "None"),
                ("Dimensions", ", ".join(plan["dimensions"]) or "None"),
                ("Time", ", ".join(plan["time_columns"]) or "None"),
                ("Identifiers", ", ".join(plan["identifiers"]) or "None"),
            ],
        ),
        "",
        "## Key Metrics",
        "",
        _table(
            ["Metric", "Value"],
            [(key.replace("_", " ").title(), _format(value)) for key, value in kpis.items()],
        ),
        "",
        "## Key Findings",
        "",
        "\n".join(f"- {item}" for item in analysis.get("insights", [])),
        "",
        "## Dataset Quality",
        "",
        _quality(schema_profile, quality_report),
        "",
        "## Numeric Measures",
        "",
        _measure_table(analysis.get("measure_summaries", [])),
        "",
        "## Recommendations",
        "",
        "\n".join(f"- {item}" for item in analysis.get("recommendations", [])),
        "",
        "## Charts And Dashboard",
        "",
        _table(
            ["Artifact", "ID"], [(item.metadata.get("title", "Chart"), item.id) for item in charts]
        ),
        "",
        "## Assumptions",
        "",
        "- Column roles were inferred from names, observed types, cardinality, and task intent.",
        (
            "- Numeric parsing treats common currency symbols, commas, percentages, "
            "and parentheses as formatting."
        ),
        "",
        "## Limitations",
        "",
        "\n".join(f"- {item}" for item in analysis.get("limitations", [])),
    ]
    return "\n".join(lines).strip() + "\n"


def _quality(schema, quality):
    rows = []
    if schema:
        rows.extend([("Rows", schema.get("row_count")), ("Columns", schema.get("column_count"))])
    if quality:
        rows.extend(
            [
                ("Missing cells", quality.get("missing_cells")),
                ("Duplicate rows", quality.get("duplicate_row_count")),
            ]
        )
    return _table(["Check", "Value"], rows) if rows else "No quality artifact was available."


def _measure_table(items):
    return (
        _table(
            ["Measure", "Count", "Mean", "Median", "Minimum", "Maximum"],
            [
                (
                    item["column"],
                    item["count"],
                    _format(item["mean"]),
                    _format(item["median"]),
                    _format(item["min"]),
                    _format(item["max"]),
                )
                for item in items
            ],
        )
        if items
        else "No numeric measures were detected."
    )


def _table(headers, rows):
    if not rows:
        return "No applicable values were available."
    header = "| " + " | ".join(str(item) for item in headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _format(value):
    return f"{value:,.2f}" if isinstance(value, float) else str(value)

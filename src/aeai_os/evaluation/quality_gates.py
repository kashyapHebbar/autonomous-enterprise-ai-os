from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from aeai_os.runs.models import ArtifactRecord
from aeai_os.schemas.enums import ArtifactType


@dataclass(frozen=True)
class EvaluationOutcome:
    score: float
    passed: bool
    checks: list[dict[str, Any]]
    target_artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "passed": self.passed,
            "checks": self.checks,
            "target_artifact_id": self.target_artifact_id,
        }


def evaluate_procurement_outputs(
    analysis: dict[str, Any],
    report_markdown: str,
    artifacts: list[ArtifactRecord],
    chart_payloads: list[dict[str, Any]],
    target_artifact_id: str | None = None,
) -> EvaluationOutcome:
    checks = [
        _artifact_completeness_check(artifacts),
        _task_completion_check(report_markdown=report_markdown, artifacts=artifacts),
        _data_consistency_check(
            analysis=analysis,
            report_markdown=report_markdown,
            chart_payloads=chart_payloads,
        ),
        _assumption_disclosure_check(report_markdown),
    ]
    required_checks = [check for check in checks if check["required"]]
    passed = all(check["passed"] for check in required_checks)
    score = round(
        sum(float(check["score"]) for check in required_checks) / len(required_checks),
        4,
    )
    return EvaluationOutcome(
        score=score,
        passed=passed,
        checks=checks,
        target_artifact_id=target_artifact_id,
    )


def extract_embedded_chart_payload(document: str) -> dict[str, Any] | None:
    match = re.search(
        r'<script[^>]*data-role="chart-data"[^>]*>(.*?)</script>',
        document,
        flags=re.DOTALL,
    )
    if match is None:
        return None
    payload = match.group(1).strip()
    if not payload:
        return None
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        return None
    return parsed


def _artifact_completeness_check(artifacts: list[ArtifactRecord]) -> dict[str, Any]:
    artifact_types = {artifact.type for artifact in artifacts}
    chart_count = sum(1 for artifact in artifacts if artifact.type == ArtifactType.CHART)
    required_types = {
        ArtifactType.KPI_TABLE,
        ArtifactType.DASHBOARD,
        ArtifactType.REPORT,
    }
    missing_types = sorted(artifact_type.value for artifact_type in required_types - artifact_types)
    passed = not missing_types and chart_count >= 4
    details = {
        "missing_artifact_types": missing_types,
        "chart_count": chart_count,
        "required_chart_count": 4,
    }
    return _check(
        name="artifact_completeness",
        passed=passed,
        score=1.0 if passed else 0.0,
        message=(
            "Required KPI, dashboard, report, and chart artifacts are present."
            if passed
            else "Required evaluation input artifacts are incomplete."
        ),
        details=details,
    )


def _task_completion_check(
    report_markdown: str,
    artifacts: list[ArtifactRecord],
) -> dict[str, Any]:
    has_report_title = "# Procurement Analysis Report" in report_markdown
    has_dashboard = any(artifact.type == ArtifactType.DASHBOARD for artifact in artifacts)
    has_recommendations = "## Recommendations" in report_markdown
    passed = has_report_title and has_dashboard and has_recommendations
    return _check(
        name="task_completion",
        passed=passed,
        score=_ratio([has_report_title, has_dashboard, has_recommendations]),
        message=(
            "The report and dashboard complete the procurement analysis task."
            if passed
            else "The workflow output is missing a report, dashboard, or recommendations."
        ),
        details={
            "has_report_title": has_report_title,
            "has_dashboard": has_dashboard,
            "has_recommendations": has_recommendations,
        },
    )


def _data_consistency_check(
    analysis: dict[str, Any],
    report_markdown: str,
    chart_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    total_spend = _number(analysis["kpis"]["total_spend"])
    expected_total = _money(total_spend)
    report_matches = expected_total in report_markdown
    chart_total = _find_chart_metric(chart_payloads, "Total spend")
    chart_matches = chart_total is not None and abs(_number(chart_total) - total_spend) <= 0.0001
    passed = report_matches and chart_matches
    return _check(
        name="data_consistency",
        passed=passed,
        score=_ratio([report_matches, chart_matches]),
        message=(
            "KPI total spend is consistent across report and chart artifacts."
            if passed
            else "KPI total spend differs across computed data, report, or chart artifacts."
        ),
        details={
            "computed_total_spend": total_spend,
            "expected_report_value": expected_total,
            "report_matches": report_matches,
            "chart_total_spend": chart_total,
            "chart_matches": chart_matches,
        },
    )


def _assumption_disclosure_check(report_markdown: str) -> dict[str, Any]:
    has_assumptions = "## Assumptions" in report_markdown
    has_limitations = "## Limitations" in report_markdown
    passed = has_assumptions and has_limitations
    return _check(
        name="assumption_disclosure",
        passed=passed,
        score=_ratio([has_assumptions, has_limitations]),
        message=(
            "Report includes assumptions and limitations."
            if passed
            else "Report is missing assumptions or limitations disclosure."
        ),
        details={
            "has_assumptions": has_assumptions,
            "has_limitations": has_limitations,
        },
    )


def _find_chart_metric(chart_payloads: list[dict[str, Any]], metric_name: str) -> Any:
    for payload in chart_payloads:
        for item in payload.get("data", []):
            if item.get("metric") == metric_name:
                return item.get("value")
    return None


def _check(
    name: str,
    passed: bool,
    score: float,
    message: str,
    details: dict[str, Any],
    required: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": passed,
        "score": round(score, 4),
        "required": required,
        "message": message,
        "details": details,
    }


def _ratio(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _money(value: Any) -> str:
    return f"${_number(value):,.2f}"

"""Upgrade 11: deterministic intelligence and reliability summaries.

Only existing, tenant-visible completed run artifacts are inspected. Never sends
raw business data to an LLM; never recomputes or merges figures across datasets.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

from aeai_os.schemas.enums import ArtifactType, RunStatus
from aeai_os.storage.artifacts import ArtifactStorageError


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return round(float(value), 4)


def _short_text(value: Any, length: int = 220) -> str:
    return str(value).strip()[:length] if isinstance(value, str) else ""


def build_overview(
    repository: Any, artifact_store: Any, user: Any, *, max_runs: int = 12
) -> dict[str, Any]:
    """Overview is explicitly a collection of *per-run* facts, not rolled-up money."""
    visible_runs = [
        run
        for run in repository.list_runs()
        if user.can_access(
            run.metadata.get("organization_id", "local-org"),
            run.metadata.get("workspace_id", "default"),
        )
    ]
    completed = sorted(
        (run for run in visible_runs if run.status == RunStatus.COMPLETED),
        key=lambda run: run.updated_at,
        reverse=True,
    )
    cards: list[dict[str, Any]] = []
    for run in completed[:max_runs]:
        source = next(
            (
                item
                for item in reversed(repository.list_artifacts(run.id))
                if item.type == ArtifactType.KPI_TABLE
                and item.metadata.get("source") == "analytics_code_agent"
                and item.metadata.get("format") == "json"
            ),
            None,
        )
        if source is None:
            continue
        try:
            analysis = artifact_store.read_json(source.uri)
        except (ArtifactStorageError, ValueError, OSError, KeyError, TypeError):
            continue
        if not isinstance(analysis, dict) or not isinstance(analysis.get("kpis"), dict):
            continue
        kpis = analysis["kpis"]
        kind = analysis.get("analysis_type")
        approved = (
            (
                "total_spend",
                "anomaly_count",
                "high_risk_count",
                "estimated_savings",
                "supplier_count",
                "outlier_count",
            )
            if kind == "procurement"
            else ("row_count", "outlier_count", "completeness", "duplicate_row_count")
        )
        figures = {
            name: number for name in approved if (number := _finite(kpis.get(name))) is not None
        }
        trends: list[dict[str, Any]] = []
        trend_name = "spend_trend" if kind == "procurement" else "time_series"
        for item in (analysis.get(trend_name) or [])[:24]:
            if not isinstance(item, dict):
                continue
            label = _short_text(item.get("month") or item.get("period"), 30)
            amount = _finite(item.get("spend") if kind == "procurement" else item.get("value"))
            if label and amount is not None:
                trends.append({"label": label, "value": amount})
        recommendations = [
            text
            for value in (analysis.get("recommendations") or [])[:3]
            if (text := _short_text(value))
        ]
        insights = [
            text for value in (analysis.get("insights") or [])[:4] if (text := _short_text(value))
        ]
        # Business-friendly next steps are *deterministic suggestions*, grounded in
        # existing saved KPIs. They are not generated accusations or new LLM facts.
        if kind == "procurement" and not recommendations:
            if figures.get("high_risk_count", 0) > 0:
                recommendations.append(
                    "Prioritize reviewing high-risk purchasing alerts with an authorized reviewer."
                )
            if figures.get("anomaly_count", 0) > 0:
                recommendations.append(
                    "Verify flagged transactions against source invoices before deciding on action."
                )
            if figures.get("estimated_savings", 0) > 0:
                recommendations.append(
                    "Validate estimated savings opportunities with procurement owners before budgeting them."  # noqa: E501
                )
            if figures.get("outlier_count", 0) > 0 and len(recommendations) < 3:
                recommendations.append(
                    "Check unusually large purchases for legitimate business explanations."
                )
            recommendations = recommendations[:3]
        # Only predefined aggregate savings fields, no supplier identifiers or row detail.
        opportunities = []
        for item in (analysis.get("savings_opportunities") or [])[:3]:
            if not isinstance(item, dict):
                continue
            estimate = _finite(item.get("estimated_savings"))
            description = _short_text(
                item.get("description") or item.get("reason") or item.get("opportunity")
            )
            if estimate is not None or description:
                opportunities.append({"description": description, "estimated_savings": estimate})
        cards.append(
            {
                "run_id": run.id,
                "task": _short_text(run.task, 170),
                "updated_at": run.updated_at.isoformat(),
                "artifact_id": source.id,
                "analysis_type": kind,
                "currency": _short_text((analysis.get("dataset") or {}).get("currency"), 5) or None,
                "figures": figures,
                "trend": trends,
                "insights": insights,
                "recommendations": recommendations,
                "opportunities": opportunities,
            }
        )
    return {
        "completed_runs": len(completed),
        "analyzed_runs": len(cards),
        "latest": cards[0] if cards else None,
        "analyses": cards[:8],
        "note": "Figures and trends belong to their individual saved runs and must not be added across investigations.",  # noqa: E501
    }


def workspace_health(repository: Any, user: Any, *, repository_backend: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    stale: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for run in repository.list_runs():
        if not user.can_access(
            run.metadata.get("organization_id", "local-org"),
            run.metadata.get("workspace_id", "default"),
        ):
            continue
        updated = run.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if run.status in {RunStatus.RUNNING, RunStatus.QUEUED} and updated < now - timedelta(
            minutes=30
        ):
            stale.append(
                {
                    "run_id": run.id,
                    "task": _short_text(run.task, 120),
                    "updated_at": updated.isoformat(),
                    "status": str(run.status),
                }
            )
        if run.status == RunStatus.FAILED:
            failures.append(
                {
                    "run_id": run.id,
                    "task": _short_text(run.task, 120),
                    "updated_at": updated.isoformat(),
                    "status": str(run.status),
                }
            )
    return {
        "persistent_runs": repository_backend.strip().lower() == "sqlalchemy",
        "repository": "SQLite / SQLAlchemy"
        if repository_backend.strip().lower() == "sqlalchemy"
        else "In-memory",
        "stale_runs": sorted(stale, key=lambda item: item["updated_at"], reverse=True)[:8],
        "failed_runs": sorted(failures, key=lambda item: item["updated_at"], reverse=True)[:8],
        "auto_recovery_enabled": False,
        "message": "Stale runs require review; no automatic replay or duplicate execution is attempted.",  # noqa: E501
    }

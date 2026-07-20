from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aeai_os.data.profiling import CsvDatasetProfile

AnalysisRecipe = Literal["procurement", "generic"]

PROCUREMENT_ALIASES = {
    "supplier": {"supplier", "supplier_name", "vendor", "vendor_name"},
    "category": {
        "category",
        "spend_category",
        "commodity",
        "procurement_category",
        "expense_type",
    },
    "amount": {
        "amount",
        "amount_gbp",
        "amount_usd",
        "amount_eur",
        "amount_inr",
        "spend_amount",
        "invoice_amount",
        "net_amount",
        "total_amount",
        "transaction_amount",
        "cost",
        "spend",
    },
    "date": {
        "date",
        "invoice_date",
        "transaction_date",
        "purchase_date",
        "payment_date",
        "posting_date",
    },
}


class DatasetAnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe: AnalysisRecipe
    domain: str
    confidence: float = Field(ge=0, le=1)
    measures: list[str]
    dimensions: list[str]
    time_columns: list[str]
    identifiers: list[str]
    semantic_mappings: dict[str, str]
    goals: list[str]
    warnings: list[str]
    requires_clarification: bool = False


def build_dataset_analysis_plan(
    profile: CsvDatasetProfile,
    user_task: str,
    preferred_recipe: AnalysisRecipe | None = None,
) -> DatasetAnalysisPlan:
    normalized = {_normalize(column.name): column for column in profile.columns}
    mappings = {
        role: normalized[alias].name
        for role, aliases in PROCUREMENT_ALIASES.items()
        for alias in aliases
        if alias in normalized
    }
    procurement_ready = {"supplier", "category", "amount"}.issubset(mappings)
    procurement_intent = any(
        token in user_task.lower()
        for token in ("procurement", "supplier", "vendor", "invoice", "spend")
    )
    if preferred_recipe == "procurement" and not procurement_ready:
        missing = sorted({"supplier", "category", "amount"} - set(mappings))
        raise ValueError(
            "Procurement analysis requires semantic columns for: " + ", ".join(missing)
        )
    recipe: AnalysisRecipe = (
        "procurement"
        if preferred_recipe == "procurement" or (procurement_ready and procurement_intent)
        else "generic"
    )

    identifiers = [
        column.name
        for column in profile.columns
        if _is_identifier(column.name, column.unique_count, profile.row_count)
    ]
    time_columns = [
        column.name
        for column in profile.columns
        if column.inferred_type == "date" or _looks_temporal(column.name)
    ]
    measures = [
        column.name
        for column in profile.columns
        if column.inferred_type in {"integer", "number"}
        and column.name not in identifiers
        and column.name not in time_columns
    ]
    dimensions = [
        column.name
        for column in profile.columns
        if column.name not in identifiers
        and column.name not in time_columns
        and column.name not in measures
        and column.unique_count <= max(20, min(profile.row_count // 2, 500))
    ]
    warnings = list(profile.quality_summary.get("warnings") or [])
    if not measures:
        warnings.append(
            "No numeric measures were detected; analysis will focus on counts and quality."
        )
    if not time_columns:
        warnings.append("No time column was detected; trend analysis will be omitted.")
    confidence = 0.95 if recipe == "procurement" else _generic_confidence(profile, measures)
    return DatasetAnalysisPlan(
        recipe=recipe,
        domain="procurement" if recipe == "procurement" else "general",
        confidence=confidence,
        measures=measures[:20],
        dimensions=dimensions[:20],
        time_columns=time_columns[:10],
        identifiers=identifiers[:20],
        semantic_mappings=mappings if recipe == "procurement" else {},
        goals=_analysis_goals(user_task),
        warnings=warnings,
        requires_clarification=profile.row_count == 0,
    )


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _is_identifier(name: str, unique_count: int, row_count: int) -> bool:
    normalized = _normalize(name)
    explicit = normalized == "id" or normalized.endswith("_id") or "identifier" in normalized
    unique = row_count > 5 and unique_count / row_count >= 0.98
    return explicit or (unique and any(token in normalized for token in ("code", "number", "key")))


def _looks_temporal(name: str) -> bool:
    normalized = _normalize(name)
    return any(token in normalized for token in ("date", "time", "timestamp", "month", "year"))


def _analysis_goals(task: str) -> list[str]:
    lowered = task.lower()
    candidates = [
        ("quality", ("quality", "missing", "clean")),
        ("summary", ("analyze", "analysis", "summary", "kpi", "dashboard", "report")),
        ("trend", ("trend", "over time", "forecast", "growth")),
        ("segments", ("segment", "group", "breakdown", "compare")),
        ("outliers", ("outlier", "anomaly", "unusual", "risk")),
        ("relationships", ("correlation", "relationship", "driver")),
    ]
    goals = [name for name, terms in candidates if any(term in lowered for term in terms)]
    return goals or ["quality", "summary", "segments", "outliers"]


def _generic_confidence(profile: CsvDatasetProfile, measures: list[str]) -> float:
    if profile.row_count == 0:
        return 0.2
    typed = sum(column.inferred_type != "unknown" for column in profile.columns)
    type_ratio = typed / max(profile.column_count, 1)
    return round(min(0.9, 0.55 + type_ratio * 0.2 + bool(measures) * 0.1), 2)


def analysis_plan_from_schema(payload: dict[str, Any]) -> DatasetAnalysisPlan | None:
    plan = payload.get("analysis_plan")
    return DatasetAnalysisPlan.model_validate(plan) if isinstance(plan, dict) else None

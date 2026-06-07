from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    description: str
    required: bool = True


DEFAULT_MVP_CHECKS = [
    EvaluationCheck(
        name="artifact_completeness",
        description="Required dashboard, report, and evaluation artifacts were produced.",
    ),
    EvaluationCheck(
        name="data_consistency",
        description="Report claims and chart values match computed KPI artifacts.",
    ),
    EvaluationCheck(
        name="assumption_disclosure",
        description="Report includes assumptions and limitations.",
    ),
]

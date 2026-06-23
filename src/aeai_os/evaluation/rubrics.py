from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCheck:
    name: str
    description: str
    required: bool = True


DEFAULT_MVP_CHECKS = [
    EvaluationCheck(
        name="task_completion",
        description="The workflow produced a report, dashboard, and recommendations.",
    ),
    EvaluationCheck(
        name="artifact_completeness",
        description="Required KPI, chart, dashboard, and report artifacts were produced.",
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

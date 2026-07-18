"""Agent interfaces and registry."""

from aeai_os.agents.base import AgentInput, AgentOutput, AgentStatus
from aeai_os.agents.registry import AgentRegistry, build_default_registry

_LAZY_EXPORTS = {
    "AnalyticsCodeAgent": "aeai_os.agents.analytics_code",
    "DataRetrievalAgent": "aeai_os.agents.data_retrieval",
    "EvaluationAgent": "aeai_os.agents.evaluation",
    "ExecutionPlanSchema": "aeai_os.agents.planner",
    "PlanNodeSchema": "aeai_os.agents.planner",
    "PlannerAgent": "aeai_os.agents.planner",
    "PlannerValidationError": "aeai_os.agents.planner",
    "ReportAgent": "aeai_os.agents.report",
    "VisualizationAgent": "aeai_os.agents.visualization",
    "execution_plan_json_schema": "aeai_os.agents.planner",
    "validate_planner_output": "aeai_os.agents.planner",
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module 'aeai_os.agents' has no attribute {name!r}")
    from importlib import import_module

    module = import_module(_LAZY_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "AgentInput",
    "AgentOutput",
    "AgentRegistry",
    "AgentStatus",
    "AnalyticsCodeAgent",
    "DataRetrievalAgent",
    "EvaluationAgent",
    "ExecutionPlanSchema",
    "PlanNodeSchema",
    "PlannerAgent",
    "PlannerValidationError",
    "ReportAgent",
    "VisualizationAgent",
    "build_default_registry",
    "execution_plan_json_schema",
    "validate_planner_output",
]

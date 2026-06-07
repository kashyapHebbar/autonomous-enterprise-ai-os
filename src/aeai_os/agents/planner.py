from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.agents.registry import AgentRegistry, build_default_registry
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode, GraphValidationError
from aeai_os.schemas.enums import AgentEventType

RiskLevel = Literal["low", "medium", "high"]

PLANNER_SYSTEM_PROMPT = """You are the planner agent for an enterprise AI operating system.
Return only structured execution plans that use registered agents, dependency-safe node IDs,
required tool names, expected artifact types, and explicit risk labels."""


class PlannerValidationError(ValueError):
    pass


class PlanNodeSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=96)
    agent: str = Field(..., min_length=1, max_length=128)
    task: str = Field(..., min_length=3, max_length=2000)
    depends_on: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    risk: RiskLevel = "low"

    @field_validator("id", "agent", "task")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized

    @field_validator("depends_on", "required_tools", "expected_artifacts")
    @classmethod
    def normalize_string_list(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("List values must not be blank.")
            normalized.append(stripped)
        return normalized

    def to_execution_node(self) -> ExecutionNode:
        return ExecutionNode(
            id=self.id,
            agent=self.agent,
            task=self.task,
            depends_on=list(self.depends_on),
            required_tools=list(self.required_tools),
            expected_artifacts=list(self.expected_artifacts),
            risk=self.risk,
        )


class ExecutionPlanSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., min_length=1, max_length=96)
    user_task: str = Field(..., min_length=3, max_length=4000)
    nodes: list[PlanNodeSchema] = Field(..., min_length=1)

    @field_validator("run_id", "user_task")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized

    def to_execution_graph(self) -> ExecutionGraph:
        return ExecutionGraph(
            run_id=self.run_id,
            nodes=[node.to_execution_node() for node in self.nodes],
        )


class PlannerAgent:
    agent_type = "planner"

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            plan = self.create_plan(
                run_id=agent_input.run_id,
                user_task=agent_input.task,
                dataset_artifact_id=agent_input.context.get("dataset_artifact_id"),
            )
        except PlannerValidationError as exc:
            return AgentOutput(
                status="failed",
                summary="Planner failed to create a valid execution graph.",
                errors=[str(exc)],
            )

        return AgentOutput(
            status="succeeded",
            summary=f"Created execution graph with {len(plan.nodes)} nodes.",
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "Planner generated a validated execution graph.",
                    "node_count": len(plan.nodes),
                }
            ],
            metrics={"plan": plan.model_dump()},
        )

    def create_plan(
        self,
        run_id: str,
        user_task: str,
        dataset_artifact_id: str | None = None,
    ) -> ExecutionPlanSchema:
        normalized_task = user_task.strip()
        if not _looks_like_procurement_dashboard_task(normalized_task):
            raise PlannerValidationError(
                "Planner currently supports procurement analytics dashboard/report workflows."
            )

        plan = ExecutionPlanSchema(
            run_id=run_id,
            user_task=normalized_task,
            nodes=_procurement_dashboard_nodes(dataset_artifact_id=dataset_artifact_id),
        )
        return validate_planner_output(plan.model_dump(), self._registry)


def validate_planner_output(
    payload: dict[str, Any],
    registry: AgentRegistry | None = None,
) -> ExecutionPlanSchema:
    try:
        plan = ExecutionPlanSchema.model_validate(payload)
    except ValidationError as exc:
        raise PlannerValidationError(
            f"Planner output does not match the plan schema: {exc}"
        ) from exc

    graph = plan.to_execution_graph()
    try:
        graph.validate(set((registry or build_default_registry()).list_agent_types()))
    except GraphValidationError as exc:
        raise PlannerValidationError(f"Planner output failed graph validation: {exc}") from exc

    return plan


def execution_plan_json_schema() -> dict[str, Any]:
    return ExecutionPlanSchema.model_json_schema()


def _looks_like_procurement_dashboard_task(user_task: str) -> bool:
    lowered = user_task.lower()
    has_procurement_context = any(
        keyword in lowered for keyword in {"procurement", "supplier", "spend", "invoice"}
    )
    has_analysis_goal = any(
        keyword in lowered for keyword in {"analyze", "analysis", "dashboard", "report", "kpi"}
    )
    return has_procurement_context and has_analysis_goal


def _procurement_dashboard_nodes(dataset_artifact_id: str | None) -> list[PlanNodeSchema]:
    dataset_context = (
        f" using dataset artifact {dataset_artifact_id}" if dataset_artifact_id else ""
    )
    return [
        PlanNodeSchema(
            id="data_profile",
            agent="data_retrieval",
            task=f"Profile the procurement dataset{dataset_context}.",
            required_tools=["dataset_reader", "schema_profiler", "quality_checker"],
            expected_artifacts=["schema_profile", "quality_report"],
            risk="low",
        ),
        PlanNodeSchema(
            id="analytics",
            agent="analytics_code",
            task=(
                "Compute procurement KPIs, supplier spend, category trends, outliers, "
                "and savings opportunities."
            ),
            depends_on=["data_profile"],
            required_tools=["dataframe_query", "python_analysis", "code_artifact_writer"],
            expected_artifacts=["kpi_table", "code"],
            risk="medium",
        ),
        PlanNodeSchema(
            id="visualization",
            agent="visualization",
            task=(
                "Create charts and a dashboard for procurement KPIs, trends, supplier "
                "concentration, categories, and anomalies."
            ),
            depends_on=["analytics"],
            required_tools=["chart_renderer", "dashboard_renderer"],
            expected_artifacts=["chart", "dashboard"],
            risk="low",
        ),
        PlanNodeSchema(
            id="report",
            agent="report",
            task=(
                "Generate a final report with insights, charts, recommendations, "
                "assumptions, and limitations."
            ),
            depends_on=["analytics", "visualization"],
            required_tools=["artifact_reader", "markdown_report_writer"],
            expected_artifacts=["report"],
            risk="low",
        ),
        PlanNodeSchema(
            id="evaluation",
            agent="evaluation",
            task=(
                "Evaluate artifact completeness and consistency between computed KPIs, "
                "dashboard charts, and report claims."
            ),
            depends_on=["visualization", "report"],
            required_tools=["artifact_reader", "deterministic_evaluator"],
            expected_artifacts=["evaluation"],
            risk="low",
        ),
    ]

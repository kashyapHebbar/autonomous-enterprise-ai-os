import pytest

from aeai_os.agents.base import AgentInput
from aeai_os.agents.planner import (
    PlannerAgent,
    PlannerValidationError,
    execution_plan_json_schema,
    validate_planner_output,
)
from aeai_os.agents.registry import build_default_registry
from aeai_os.schemas.enums import AgentEventType


def test_planner_returns_valid_procurement_dashboard_graph():
    registry = build_default_registry()
    planner = PlannerAgent(registry=registry)

    plan = planner.create_plan(
        run_id="run_123",
        user_task="Analyze this procurement dataset and create a dashboard.",
        dataset_artifact_id="artifact_dataset",
    )
    graph = plan.to_execution_graph()

    graph.validate(set(registry.list_agent_types()))
    assert [node.id for node in graph.nodes] == [
        "data_profile",
        "analytics",
        "visualization",
        "report",
        "evaluation",
    ]
    assert graph.nodes[0].required_tools == [
        "dataset_reader",
        "schema_profiler",
        "quality_checker",
    ]
    assert graph.nodes[1].depends_on == ["data_profile"]
    assert graph.nodes[1].expected_artifacts == ["kpi_table", "code"]
    assert graph.nodes[1].risk == "medium"


def test_planner_execute_returns_structured_plan_metric():
    output = PlannerAgent().execute(
        AgentInput(
            run_id="run_123",
            node_id="planner",
            task="Analyze procurement spend and create a dashboard.",
            context={"dataset_artifact_id": "artifact_dataset"},
        )
    )

    assert output.status == "succeeded"
    assert output.metrics["plan"]["run_id"] == "run_123"
    assert output.events[0]["event_type"] == AgentEventType.LOG


def test_planner_rejects_unsupported_task_with_actionable_error():
    output = PlannerAgent().execute(
        AgentInput(
            run_id="run_123",
            node_id="planner",
            task="Write a poem about cloud infrastructure.",
        )
    )

    assert output.status == "failed"
    assert "procurement analytics dashboard" in output.errors[0]


def test_validate_planner_output_rejects_invalid_plan_with_actionable_error():
    invalid_payload = {
        "run_id": "run_123",
        "user_task": "Analyze procurement spend.",
        "nodes": [
            {
                "id": "analytics",
                "agent": "analytics_code",
                "task": "Compute KPIs",
                "depends_on": ["missing_profile"],
                "required_tools": ["python_analysis"],
                "expected_artifacts": ["spreadsheet"],
                "risk": "medium",
            }
        ],
    }

    with pytest.raises(PlannerValidationError) as exc_info:
        validate_planner_output(invalid_payload, build_default_registry())

    message = str(exc_info.value)
    assert "Planner output failed graph validation" in message
    assert "spreadsheet" in message or "missing_profile" in message


def test_execution_plan_schema_is_available_for_structured_llm_output():
    schema = execution_plan_json_schema()

    assert schema["title"] == "ExecutionPlanSchema"
    assert "nodes" in schema["properties"]

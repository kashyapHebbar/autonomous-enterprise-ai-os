from aeai_os.agents.registry import build_default_registry
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode, GraphValidationError


def test_execution_graph_validates_known_agents_and_dependencies():
    registry = build_default_registry()
    graph = ExecutionGraph(
        run_id="run_123",
        nodes=[
            ExecutionNode(id="profile", agent="data_retrieval", task="Profile dataset"),
            ExecutionNode(
                id="analytics",
                agent="analytics_code",
                task="Compute KPIs",
                depends_on=["profile"],
            ),
        ],
    )

    graph.validate(set(registry.list_agent_types()))


def test_execution_graph_rejects_cycles():
    registry = build_default_registry()
    graph = ExecutionGraph(
        run_id="run_123",
        nodes=[
            ExecutionNode(id="a", agent="planner", task="A", depends_on=["b"]),
            ExecutionNode(id="b", agent="planner", task="B", depends_on=["a"]),
        ],
    )

    try:
        graph.validate(set(registry.list_agent_types()))
    except GraphValidationError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("Expected graph validation to reject a cycle.")


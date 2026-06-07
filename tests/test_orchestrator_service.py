from __future__ import annotations

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.agents.registry import build_default_registry
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode
from aeai_os.orchestration.service import OrchestratorService, RetryPolicy
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, GraphNodeStatus, RunStatus


class StaticAgent:
    def __init__(self, agent_type: str, artifact_id: str) -> None:
        self.agent_type = agent_type
        self.artifact_id = artifact_id
        self.inputs: list[AgentInput] = []

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.inputs.append(agent_input)
        return AgentOutput(
            status="succeeded",
            summary=f"{self.agent_type} completed",
            artifacts=[self.artifact_id],
            events=[{"event_type": AgentEventType.LOG, "message": "agent completed"}],
        )


class FlakyAgent:
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type
        self.calls = 0

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.calls += 1
        if self.calls == 1:
            return AgentOutput(
                status="failed",
                summary="Transient warehouse timeout",
                errors=["warehouse timeout"],
            )
        return AgentOutput(
            status="succeeded",
            summary="Recovered on retry",
            artifacts=["profile_after_retry"],
        )


class AlwaysFailingAgent:
    agent_type = "data_retrieval"

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        return AgentOutput(
            status="failed",
            summary="Permanent failure",
            errors=["bad input"],
        )


class ApprovalAgent:
    agent_type = "deployment"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        self.calls += 1
        if "approved" not in agent_input.approvals:
            return AgentOutput(
                status="waiting_for_approval",
                summary="Deployment requires approval",
            )
        return AgentOutput(
            status="succeeded",
            summary="Deployment approved",
            artifacts=["deployment_manifest"],
        )


def test_orchestrator_executes_multistep_graph_and_checkpoints_state():
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    data_agent = StaticAgent("data_retrieval", "schema_profile")
    analytics_agent = StaticAgent("analytics_code", "kpi_table")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={
            "data_retrieval": data_agent,
            "analytics_code": analytics_agent,
        },
    )
    graph = ExecutionGraph(
        run_id=run.id,
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

    result = service.execute_run(run.id, graph)

    assert result.status == RunStatus.COMPLETED
    assert result.completed_node_ids == ["profile", "analytics"]
    assert repository.get_run(run.id).status == RunStatus.COMPLETED
    assert repository.get_checkpoint(run.id).state["artifacts"] == {
        "profile": ["schema_profile"],
        "analytics": ["kpi_table"],
    }
    assert repository.get_graph_node(run.id, "profile").status == GraphNodeStatus.COMPLETED
    assert analytics_agent.inputs[0].artifacts == ["schema_profile"]


def test_orchestrator_retries_failed_node_without_restarting_completed_work():
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    profile_agent = StaticAgent("data_retrieval", "schema_profile")
    flaky_agent = FlakyAgent("analytics_code")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={
            "data_retrieval": profile_agent,
            "analytics_code": flaky_agent,
        },
        retry_policy=RetryPolicy(max_attempts=2),
    )
    graph = ExecutionGraph(
        run_id=run.id,
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

    result = service.execute_run(run.id, graph)

    node = repository.get_graph_node(run.id, "analytics")
    event_types = [event.event_type for event in repository.list_events(run.id)]
    assert result.status == RunStatus.COMPLETED
    assert len(profile_agent.inputs) == 1
    assert flaky_agent.calls == 2
    assert node.status == GraphNodeStatus.COMPLETED
    assert node.retry_count == 1
    assert AgentEventType.ERROR in event_types


def test_orchestrator_marks_run_failed_when_retries_are_exhausted():
    repository = InMemoryRunRepository()
    run = repository.create_run("Profile procurement data.")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"data_retrieval": AlwaysFailingAgent()},
        retry_policy=RetryPolicy(max_attempts=1),
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[ExecutionNode(id="profile", agent="data_retrieval", task="Profile dataset")],
    )

    result = service.execute_run(run.id, graph)

    assert result.status == RunStatus.FAILED
    assert result.failed_node_ids == ["profile"]
    assert repository.get_run(run.id).status == RunStatus.FAILED
    assert repository.get_graph_node(run.id, "profile").status == GraphNodeStatus.FAILED
    assert repository.get_checkpoint(run.id).state["errors"] == {"profile": ["bad input"]}


def test_orchestrator_pauses_for_approval_and_resumes_after_decision():
    repository = InMemoryRunRepository()
    run = repository.create_run("Deploy validated dashboard.")
    approval_agent = ApprovalAgent()
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"deployment": approval_agent},
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="deploy",
                agent="deployment",
                task="Deploy dashboard",
                risk="high",
            )
        ],
    )

    paused = service.execute_run(run.id, graph)
    resumed = service.approve_node(run.id, "deploy", approved=True, comment="Approved for demo.")

    event_types = [event.event_type for event in repository.list_events(run.id)]
    assert paused.status == RunStatus.WAITING_FOR_APPROVAL
    assert paused.waiting_for_approval_node_id == "deploy"
    assert resumed.status == RunStatus.COMPLETED
    assert approval_agent.calls == 2
    assert repository.get_checkpoint(run.id).state["approvals"] == {"deploy": "approved"}
    assert AgentEventType.APPROVAL_REQUEST in event_types
    assert AgentEventType.APPROVAL_DECISION in event_types

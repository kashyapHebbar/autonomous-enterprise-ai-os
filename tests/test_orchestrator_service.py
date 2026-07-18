from __future__ import annotations

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.agents.registry import build_default_registry
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode
from aeai_os.orchestration.service import OrchestratorService, RetryPolicy
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType, GraphNodeStatus, RunStatus
from aeai_os.security import PolicyRule, ToolPolicyDecisionStatus, build_policy_registry_from_rules


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
    completed_events = [
        event
        for event in repository.list_events(run.id)
        if event.payload.get("message") == "Node execution completed."
    ]
    assert completed_events[-1].payload["trace_id"] == repository.get_run(run.id).trace_id
    assert completed_events[-1].payload["duration_ms"] >= 0


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


def test_orchestrator_security_gate_pauses_high_risk_tool_before_agent_execution():
    repository = InMemoryRunRepository()
    run = repository.create_run("Deploy validated dashboard.")
    deployment_agent = StaticAgent("deployment", "deployment_manifest")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"deployment": deployment_agent},
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="deploy",
                agent="deployment",
                task="Deploy dashboard",
                required_tools=["deploy_artifact"],
                risk="high",
            )
        ],
    )

    paused = service.execute_run(run.id, graph)
    events = repository.list_events(run.id)
    tool_event = next(event for event in events if event.event_type == AgentEventType.TOOL_CALL)

    assert paused.status == RunStatus.WAITING_FOR_APPROVAL
    assert deployment_agent.inputs == []
    assert tool_event.payload["agent"] == "deployment"
    assert tool_event.payload["tool"] == "deploy_artifact"
    assert tool_event.payload["decision"] == "approval_required"
    assert tool_event.payload["policy_rule_id"] == "deployment-promotion-approval"
    assert tool_event.payload["input_summary"].startswith("agent=deployment")
    assert tool_event.payload["timestamp"]

    resumed = service.approve_node(run.id, "deploy", approved=True, comment="Approved for demo.")
    approved_tool_events = [
        event
        for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.TOOL_CALL and event.payload["decision"] == "allow"
    ]

    assert resumed.status == RunStatus.COMPLETED
    assert len(deployment_agent.inputs) == 1
    assert approved_tool_events[-1].payload["approved"] is True


def test_orchestrator_security_gate_blocks_destructive_tool_before_agent_execution():
    repository = InMemoryRunRepository()
    run = repository.create_run("Delete dashboard artifact.")
    deployment_agent = StaticAgent("deployment", "deleted")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"deployment": deployment_agent},
        retry_policy=RetryPolicy(max_attempts=1),
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="delete",
                agent="deployment",
                task="Delete dashboard",
                required_tools=["delete_artifact"],
                risk="high",
            )
        ],
    )

    result = service.execute_run(run.id, graph)
    events = repository.list_events(run.id)
    tool_event = next(event for event in events if event.event_type == AgentEventType.TOOL_CALL)

    assert result.status == RunStatus.FAILED
    assert deployment_agent.inputs == []
    assert tool_event.payload["tool"] == "delete_artifact"
    assert tool_event.payload["decision"] == "block"
    assert tool_event.payload["destructive"] is True
    assert tool_event.payload["policy_rule_id"] == "destructive-action-deny"
    assert repository.get_checkpoint(run.id).state["errors"] == {
        "delete": ["delete_artifact: Destructive tool use is denied by governance policy."]
    }


def test_orchestrator_security_gate_escalates_external_connector_access():
    repository = InMemoryRunRepository()
    run = repository.create_run("Profile Snowflake procurement data.")
    data_agent = StaticAgent("data_retrieval", "schema_profile")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"data_retrieval": data_agent},
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="snowflake_profile",
                agent="data_retrieval",
                task="Profile Snowflake table",
                required_tools=["snowflake_query"],
                risk="high",
            )
        ],
    )

    paused = service.execute_run(run.id, graph)
    tool_event = next(
        event for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.TOOL_CALL
    )
    approval_request = next(
        event for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.APPROVAL_REQUEST
        and "escalation_targets" in event.payload
    )

    assert paused.status == RunStatus.WAITING_FOR_APPROVAL
    assert data_agent.inputs == []
    assert tool_event.payload["decision"] == "escalate"
    assert tool_event.payload["policy_rule_id"] == "external-connector-escalation"
    assert tool_event.payload["escalation_target"] == "platform-security"
    assert approval_request.payload["escalation_targets"] == ["platform-security"]

    resumed = service.approve_node(
        run.id,
        "snowflake_profile",
        approved=True,
        comment="Approved external connector access.",
    )

    assert resumed.status == RunStatus.COMPLETED
    assert len(data_agent.inputs) == 1


def test_orchestrator_security_gate_requires_approval_for_sensitive_artifact_access():
    repository = InMemoryRunRepository()
    run = repository.create_run("Generate report from sensitive dataset.")
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://secure/procurement.csv",
        metadata={"format": "csv", "sensitive": True},
    )
    report_agent = StaticAgent("report", "report_final")
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"report": report_agent},
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="report",
                agent="report",
                task="Write executive report",
                required_tools=["artifact_reader", "markdown_report_writer"],
            )
        ],
    )

    paused = service.execute_run(run.id, graph)
    tool_event = next(
        event for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.TOOL_CALL
        and event.payload["tool"] == "artifact_reader"
    )

    assert paused.status == RunStatus.WAITING_FOR_APPROVAL
    assert report_agent.inputs == []
    assert tool_event.payload["decision"] == "approval_required"
    assert tool_event.payload["policy_rule_id"] == "sensitive-artifact-approval"
    assert tool_event.payload["policy_context"]["artifact_sensitive"] is True


def test_orchestrator_security_gate_can_request_retry_before_agent_execution():
    repository = InMemoryRunRepository()
    run = repository.create_run("Query temporarily unavailable warehouse.")
    data_agent = StaticAgent("data_retrieval", "schema_profile")
    policy_registry = build_policy_registry_from_rules(
        [
            PolicyRule(
                id="retry-warehouse-maintenance",
                description="Retry Snowflake work during maintenance.",
                decision=ToolPolicyDecisionStatus.RETRY,
                reason="Warehouse maintenance window is active.",
                tool_patterns=["snowflake_query"],
                retry_after_seconds=60,
            )
        ]
    )
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"data_retrieval": data_agent},
        retry_policy=RetryPolicy(max_attempts=1),
        tool_permissions=policy_registry,
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="snowflake_profile",
                agent="data_retrieval",
                task="Profile Snowflake table",
                required_tools=["snowflake_query"],
            )
        ],
    )

    result = service.execute_run(run.id, graph)
    tool_event = next(
        event for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.TOOL_CALL
    )

    assert result.status == RunStatus.FAILED
    assert data_agent.inputs == []
    assert tool_event.payload["decision"] == "retry"
    assert tool_event.payload["retry_after_seconds"] == 60

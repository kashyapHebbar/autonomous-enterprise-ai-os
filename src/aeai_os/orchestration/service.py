from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any
from uuid import uuid4

from aeai_os.agents.base import Agent, AgentInput, AgentOutput
from aeai_os.agents.registry import AgentRegistry
from aeai_os.observability.tracing import current_trace_id, start_span
from aeai_os.orchestration.graph import ExecutionGraph
from aeai_os.orchestration.state import (
    LangGraphRunState,
    build_initial_state,
    output_to_state,
    sync_state_from_node_statuses,
)
from aeai_os.runs.models import AgentEventRecord, GraphNodeRecord
from aeai_os.runs.repository import (
    InMemoryRunRepository,
    RunCheckpointNotFoundError,
    utc_now,
)
from aeai_os.schemas.enums import AgentEventType, GraphNodeStatus, RunStatus
from aeai_os.security import (
    ToolPermissionRegistry,
    ToolPolicyDecision,
    ToolPolicyDecisionStatus,
    default_tool_permission_registry,
)


class OrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")


@dataclass(frozen=True)
class OrchestrationResult:
    run_id: str
    status: RunStatus
    state: LangGraphRunState
    completed_node_ids: list[str]
    failed_node_ids: list[str]
    waiting_for_approval_node_id: str | None = None


class OrchestratorService:
    """Executes validated agent graphs with repository-backed checkpoints."""

    def __init__(
        self,
        repository: InMemoryRunRepository,
        registry: AgentRegistry,
        agents: Mapping[str, Agent],
        retry_policy: RetryPolicy | None = None,
        tool_permissions: ToolPermissionRegistry | None = None,
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._agents = dict(agents)
        self._retry_policy = retry_policy or RetryPolicy()
        self._tool_permissions = tool_permissions or default_tool_permission_registry()

    def execute_run(self, run_id: str, graph: ExecutionGraph) -> OrchestrationResult:
        run = self._repository.get_run(run_id)
        with start_span(
            "orchestrator.execute_run",
            {
                "run.id": run_id,
                "run.trace_id": run.trace_id,
                "graph.node_count": len(graph.nodes),
            },
        ):
            graph.validate(set(self._registry.list_agent_types()))
            self._assert_agents_available(graph)

            now = utc_now()
            for node in graph.nodes:
                self._repository.upsert_graph_node(
                    GraphNodeRecord(
                        id=node.id,
                        run_id=run.id,
                        agent_type=node.agent,
                        status=GraphNodeStatus.PENDING,
                        depends_on=list(node.depends_on),
                        required_tools=list(node.required_tools),
                        expected_artifacts=list(node.expected_artifacts),
                        retry_count=0,
                        created_at=now,
                        updated_at=now,
                    )
                )

            state = build_initial_state(run, graph)
            self._repository.save_checkpoint(run.id, state)
            self._repository.update_status(run.id, RunStatus.RUNNING)
            return self.resume_run(run.id)

    def resume_run(self, run_id: str) -> OrchestrationResult:
        run = self._repository.get_run(run_id)
        with start_span(
            "orchestrator.resume_run",
            {
                "run.id": run_id,
                "run.trace_id": run.trace_id,
            },
        ):
            state = self._load_state(run_id)
            self._repository.update_status(run_id, RunStatus.RUNNING)

            while True:
                state = self._refresh_state_from_nodes(run_id, state)
                waiting_node_id = state["waiting_for_approval_node_id"]
                if waiting_node_id:
                    self._repository.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)
                    self._repository.save_checkpoint(run_id, state)
                    return self._result(run_id, RunStatus.WAITING_FOR_APPROVAL, state)

                nodes = self._ordered_nodes(run_id, state)
                if nodes and all(node.status == GraphNodeStatus.COMPLETED for node in nodes):
                    self._repository.update_status(run_id, RunStatus.COMPLETED)
                    self._repository.save_checkpoint(run_id, state)
                    return self._result(run_id, RunStatus.COMPLETED, state)

                terminal_failures = [
                    node
                    for node in nodes
                    if node.status == GraphNodeStatus.FAILED
                    and node.retry_count >= self._retry_policy.max_attempts
                ]
                if terminal_failures:
                    summary = "; ".join(node.id for node in terminal_failures)
                    self._repository.update_status(
                        run_id,
                        RunStatus.FAILED,
                        error_summary=f"Failed graph nodes: {summary}",
                    )
                    self._repository.save_checkpoint(run_id, state)
                    return self._result(run_id, RunStatus.FAILED, state)

                ready_nodes = [
                    node
                    for node in nodes
                    if node.status in {GraphNodeStatus.PENDING, GraphNodeStatus.FAILED}
                    and node.retry_count < self._retry_policy.max_attempts
                    and self._dependencies_completed(node, nodes)
                ]
                if not ready_nodes:
                    self._repository.update_status(
                        run_id,
                        RunStatus.FAILED,
                        error_summary="No executable graph nodes remain.",
                    )
                    self._repository.save_checkpoint(run_id, state)
                    return self._result(run_id, RunStatus.FAILED, state)

                for node in ready_nodes:
                    outcome = self._execute_node(node, state)
                    state = self._load_state(run_id)
                    if outcome == GraphNodeStatus.WAITING_FOR_APPROVAL:
                        self._repository.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)
                        return self._result(run_id, RunStatus.WAITING_FOR_APPROVAL, state)
                    if outcome == GraphNodeStatus.FAILED:
                        break

    def approve_node(
        self,
        run_id: str,
        node_id: str,
        approved: bool = True,
        comment: str | None = None,
    ) -> OrchestrationResult:
        state = self._load_state(run_id)
        node = self._repository.get_graph_node(run_id, node_id)
        if node.status != GraphNodeStatus.WAITING_FOR_APPROVAL:
            raise OrchestrationError(f"Graph node is not waiting for approval: {node_id}")

        decision = "approved" if approved else "denied"
        state["approvals"][node_id] = decision
        state["waiting_for_approval_node_id"] = None
        self._record_event(
            run_id=run_id,
            node_id=node_id,
            event_type=AgentEventType.APPROVAL_DECISION,
            payload={
                "agent": node.agent_type,
                "approved": approved,
                "comment": comment,
                "decision": decision,
                "timestamp": utc_now().isoformat(),
            },
        )

        if not approved:
            failed = replace(
                node,
                status=GraphNodeStatus.FAILED,
                finished_at=utc_now(),
                updated_at=utc_now(),
            )
            self._repository.upsert_graph_node(failed)
            state = self._refresh_state_from_nodes(run_id, state)
            self._repository.save_checkpoint(run_id, state)
            self._repository.update_status(
                run_id,
                RunStatus.FAILED,
                error_summary=f"Approval denied for node: {node_id}",
            )
            return self._result(run_id, RunStatus.FAILED, state)

        pending = replace(
            node,
            status=GraphNodeStatus.PENDING,
            updated_at=utc_now(),
        )
        self._repository.upsert_graph_node(pending)
        state = self._refresh_state_from_nodes(run_id, state)
        self._repository.save_checkpoint(run_id, state)
        return self.resume_run(run_id)

    def retry_failed_node(self, run_id: str, node_id: str) -> OrchestrationResult:
        state = self._load_state(run_id)
        node = self._repository.get_graph_node(run_id, node_id)
        if node.status != GraphNodeStatus.FAILED:
            raise OrchestrationError(f"Graph node is not failed: {node_id}")

        retryable = replace(
            node,
            status=GraphNodeStatus.PENDING,
            retry_count=0,
            finished_at=None,
            updated_at=utc_now(),
        )
        self._repository.upsert_graph_node(retryable)
        state = self._refresh_state_from_nodes(run_id, state)
        self._repository.save_checkpoint(run_id, state)
        return self.resume_run(run_id)

    def _execute_node(
        self,
        node: GraphNodeRecord,
        state: LangGraphRunState,
    ) -> GraphNodeStatus:
        started = utc_now()
        started_at_monotonic = perf_counter()
        with start_span(
            "agent.node",
            {
                "run.id": node.run_id,
                "run.trace_id": self._repository.get_run(node.run_id).trace_id,
                "agent.type": node.agent_type,
                "node.id": node.id,
                "node.attempt": node.retry_count + 1,
            },
        ) as span:
            running = replace(
                node,
                status=GraphNodeStatus.RUNNING,
                started_at=node.started_at or started,
                updated_at=started,
            )
            self._repository.upsert_graph_node(running)
            self._record_event(
                run_id=node.run_id,
                node_id=node.id,
                event_type=AgentEventType.LOG,
                payload={
                    "agent": node.agent_type,
                    "message": "Node execution started.",
                    "attempt": node.retry_count + 1,
                    "status": GraphNodeStatus.RUNNING.value,
                    "timestamp": utc_now().isoformat(),
                },
            )
            self._repository.save_checkpoint(
                node.run_id,
                self._refresh_state_from_nodes(node.run_id, state),
            )

            security_output = self._authorize_node_tools(running, state)
            if security_output is not None:
                if security_output.status == "waiting_for_approval":
                    outcome = self._pause_for_approval(running, state, security_output)
                else:
                    outcome = self._fail_node(running, state, security_output)
                _set_node_span_result(span, outcome, started_at_monotonic)
                return outcome

            output = self._call_agent(running, state)
            for event in output.events:
                self._record_event(
                    run_id=node.run_id,
                    node_id=node.id,
                    event_type=str(event.get("event_type", AgentEventType.LOG)),
                    payload={key: value for key, value in event.items() if key != "event_type"},
                )

            if output.status == "succeeded":
                outcome = self._complete_node(running, state, output)
            elif output.status == "waiting_for_approval":
                outcome = self._pause_for_approval(running, state, output)
            else:
                outcome = self._fail_node(running, state, output)
            _set_node_span_result(span, outcome, started_at_monotonic)
            return outcome

    def _call_agent(self, node: GraphNodeRecord, state: LangGraphRunState) -> AgentOutput:
        agent = self._agents[node.agent_type]
        approval = state["approvals"].get(node.id)
        agent_input = AgentInput(
            run_id=node.run_id,
            node_id=node.id,
            task=self._plan_item(state, node.id)["task"],
            context={"state": deepcopy(state)},
            artifacts=self._known_artifacts(state),
            approvals=([approval] if approval else []),
        )
        try:
            return agent.execute(agent_input)
        except Exception as exc:  # pragma: no cover - defensive guard around plugin agents.
            return AgentOutput(
                status="failed",
                summary=f"Agent raised {type(exc).__name__}: {exc}",
                errors=[str(exc)],
            )

    def _authorize_node_tools(
        self,
        node: GraphNodeRecord,
        state: LangGraphRunState,
    ) -> AgentOutput | None:
        if not node.required_tools:
            return None

        approved = state["approvals"].get(node.id) == "approved"
        task = self._plan_item(state, node.id)["task"]
        input_summary = _summarize_tool_input(node=node, task=task)
        decisions = [
            self._tool_permissions.evaluate(
                tool,
                input_summary=input_summary,
                approved=approved,
            )
            for tool in node.required_tools
        ]
        for decision in decisions:
            self._record_tool_audit_event(node, decision)

        blocked = [
            decision
            for decision in decisions
            if decision.decision == ToolPolicyDecisionStatus.BLOCK
        ]
        if blocked:
            return AgentOutput(
                status="failed",
                summary="Security policy blocked one or more required tools.",
                errors=[f"{decision.tool}: {decision.reason}" for decision in blocked],
                metrics={
                    "tool_policy_decisions": [decision.model_dump() for decision in decisions]
                },
            )

        approval_required = [
            decision
            for decision in decisions
            if decision.decision == ToolPolicyDecisionStatus.APPROVAL_REQUIRED
        ]
        if approval_required:
            return AgentOutput(
                status="waiting_for_approval",
                summary="Security approval is required for high-risk tool calls.",
                events=[
                    {
                        "event_type": AgentEventType.APPROVAL_REQUEST,
                        "message": "Tool permission policy requires approval.",
                        "tools": [decision.tool for decision in approval_required],
                    }
                ],
                metrics={
                    "tool_policy_decisions": [decision.model_dump() for decision in decisions]
                },
            )

        return None

    def _record_tool_audit_event(
        self,
        node: GraphNodeRecord,
        decision: ToolPolicyDecision,
    ) -> None:
        with start_span(
            "tool.policy_decision",
            {
                "run.id": node.run_id,
                "agent.type": node.agent_type,
                "node.id": node.id,
                "tool.name": decision.tool,
                "tool.risk": decision.risk.value,
                "tool.decision": decision.decision.value,
                "tool.approval_required": decision.approval_required,
                "tool.destructive": decision.destructive,
            },
        ):
            self._record_event(
                run_id=node.run_id,
                node_id=node.id,
                event_type=AgentEventType.TOOL_CALL,
                payload={
                    "agent": node.agent_type,
                    "tool": decision.tool,
                    "permission_level": (
                        decision.permission_level.value if decision.permission_level else None
                    ),
                    "risk": decision.risk.value,
                    "decision": decision.decision.value,
                    "input_summary": decision.input_summary,
                    "reason": decision.reason,
                    "approval_required": decision.approval_required,
                    "approved": decision.approved,
                    "destructive": decision.destructive,
                    "timestamp": utc_now().isoformat(),
                },
            )

    def _complete_node(
        self,
        node: GraphNodeRecord,
        state: LangGraphRunState,
        output: AgentOutput,
    ) -> GraphNodeStatus:
        completed = replace(
            node,
            status=GraphNodeStatus.COMPLETED,
            finished_at=utc_now(),
            updated_at=utc_now(),
        )
        state["agent_outputs"][node.id] = output_to_state(output)
        state["artifacts"][node.id] = list(output.artifacts)
        state["errors"].pop(node.id, None)
        self._repository.upsert_graph_node(completed)
        self._record_event(
            run_id=node.run_id,
            node_id=node.id,
            event_type=AgentEventType.LOG,
            payload={
                "agent": node.agent_type,
                "message": "Node execution completed.",
                "summary": output.summary,
                "status": GraphNodeStatus.COMPLETED.value,
                "artifacts": list(output.artifacts),
                "duration_ms": _node_duration_ms(node),
                "timestamp": utc_now().isoformat(),
            },
        )
        self._repository.save_checkpoint(
            node.run_id,
            self._refresh_state_from_nodes(node.run_id, state),
        )
        return GraphNodeStatus.COMPLETED

    def _pause_for_approval(
        self,
        node: GraphNodeRecord,
        state: LangGraphRunState,
        output: AgentOutput,
    ) -> GraphNodeStatus:
        waiting = replace(
            node,
            status=GraphNodeStatus.WAITING_FOR_APPROVAL,
            updated_at=utc_now(),
        )
        state["agent_outputs"][node.id] = output_to_state(output)
        state["waiting_for_approval_node_id"] = node.id
        self._repository.upsert_graph_node(waiting)
        self._record_event(
            run_id=node.run_id,
            node_id=node.id,
            event_type=AgentEventType.APPROVAL_REQUEST,
            payload={
                "agent": node.agent_type,
                "summary": output.summary,
                "errors": output.errors,
                "status": GraphNodeStatus.WAITING_FOR_APPROVAL.value,
                "duration_ms": _node_duration_ms(node),
                "timestamp": utc_now().isoformat(),
            },
        )
        self._repository.save_checkpoint(
            node.run_id,
            self._refresh_state_from_nodes(node.run_id, state),
        )
        return GraphNodeStatus.WAITING_FOR_APPROVAL

    def _fail_node(
        self,
        node: GraphNodeRecord,
        state: LangGraphRunState,
        output: AgentOutput,
    ) -> GraphNodeStatus:
        retry_count = node.retry_count + 1
        retryable = retry_count < self._retry_policy.max_attempts
        failed = replace(
            node,
            status=(GraphNodeStatus.PENDING if retryable else GraphNodeStatus.FAILED),
            retry_count=retry_count,
            finished_at=(None if retryable else utc_now()),
            updated_at=utc_now(),
        )
        state["agent_outputs"][node.id] = output_to_state(output)
        state["errors"].setdefault(node.id, []).extend(output.errors or [output.summary])
        self._repository.upsert_graph_node(failed)
        self._record_event(
            run_id=node.run_id,
            node_id=node.id,
            event_type=AgentEventType.ERROR,
            payload={
                "agent": node.agent_type,
                "summary": output.summary,
                "errors": output.errors,
                "status": failed.status.value,
                "retryable": retryable,
                "retry_count": retry_count,
                "duration_ms": _node_duration_ms(node),
                "timestamp": utc_now().isoformat(),
            },
        )
        self._repository.save_checkpoint(
            node.run_id,
            self._refresh_state_from_nodes(node.run_id, state),
        )
        return failed.status

    def _refresh_state_from_nodes(
        self,
        run_id: str,
        state: LangGraphRunState,
    ) -> LangGraphRunState:
        nodes = self._ordered_nodes(run_id, state)
        statuses = {node.id: node.status for node in nodes}
        return sync_state_from_node_statuses(state, statuses)

    def _load_state(self, run_id: str) -> LangGraphRunState:
        try:
            return self._repository.get_checkpoint(run_id).state  # type: ignore[return-value]
        except RunCheckpointNotFoundError as exc:
            raise OrchestrationError(f"No checkpoint exists for run: {run_id}") from exc

    def _result(
        self,
        run_id: str,
        status: RunStatus,
        state: LangGraphRunState,
    ) -> OrchestrationResult:
        refreshed = self._refresh_state_from_nodes(run_id, state)
        return OrchestrationResult(
            run_id=run_id,
            status=status,
            state=refreshed,
            completed_node_ids=list(refreshed["completed_node_ids"]),
            failed_node_ids=list(refreshed["failed_node_ids"]),
            waiting_for_approval_node_id=refreshed["waiting_for_approval_node_id"],
        )

    def _assert_agents_available(self, graph: ExecutionGraph) -> None:
        missing = sorted({node.agent for node in graph.nodes if node.agent not in self._agents})
        if missing:
            raise OrchestrationError(f"No executable agent registered for: {', '.join(missing)}")

    def _ordered_nodes(
        self,
        run_id: str,
        state: LangGraphRunState,
    ) -> list[GraphNodeRecord]:
        nodes_by_id = {node.id: node for node in self._repository.list_graph_nodes(run_id)}
        return [nodes_by_id[item["id"]] for item in state["plan"] if item["id"] in nodes_by_id]

    @staticmethod
    def _dependencies_completed(
        node: GraphNodeRecord,
        nodes: list[GraphNodeRecord],
    ) -> bool:
        statuses = {candidate.id: candidate.status for candidate in nodes}
        return all(
            statuses[dependency] == GraphNodeStatus.COMPLETED for dependency in node.depends_on
        )

    @staticmethod
    def _plan_item(state: LangGraphRunState, node_id: str) -> dict[str, Any]:
        for item in state["plan"]:
            if item["id"] == node_id:
                return item
        raise OrchestrationError(f"Node is missing from state plan: {node_id}")

    @staticmethod
    def _known_artifacts(state: LangGraphRunState) -> list[str]:
        artifacts: list[str] = []
        for node_artifacts in state["artifacts"].values():
            artifacts.extend(node_artifacts)
        return artifacts

    def _record_event(
        self,
        run_id: str,
        node_id: str,
        event_type: AgentEventType | str,
        payload: dict[str, Any],
    ) -> None:
        run = self._repository.get_run(run_id)
        enriched_payload = deepcopy(payload)
        enriched_payload.setdefault("trace_id", run.trace_id)
        active_trace_id = current_trace_id()
        if active_trace_id:
            enriched_payload.setdefault("otel_trace_id", active_trace_id)
        self._repository.add_event(
            AgentEventRecord(
                id=f"event_{uuid4().hex}",
                run_id=run_id,
                node_id=node_id,
                event_type=str(event_type),
                payload=enriched_payload,
                created_at=utc_now(),
            )
        )


def _set_node_span_result(
    span: Any,
    outcome: GraphNodeStatus,
    started_at_monotonic: float,
) -> None:
    span.set_attribute("node.status", outcome.value)
    span.set_attribute("node.duration_ms", round((perf_counter() - started_at_monotonic) * 1000, 3))
    if outcome == GraphNodeStatus.FAILED:
        span.set_attribute("error", True)


def _node_duration_ms(node: GraphNodeRecord) -> float | None:
    if node.started_at is None:
        return None
    return round(max((utc_now() - node.started_at).total_seconds(), 0.0) * 1000, 3)


def _summarize_tool_input(node: GraphNodeRecord, task: str) -> str:
    summary = f"agent={node.agent_type}; node={node.id}; task={task.strip()}"
    if len(summary) <= 240:
        return summary
    return summary[:237] + "..."

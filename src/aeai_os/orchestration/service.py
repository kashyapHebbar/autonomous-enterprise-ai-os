from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from aeai_os.agents.base import Agent, AgentInput, AgentOutput
from aeai_os.agents.registry import AgentRegistry
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
    ) -> None:
        self._repository = repository
        self._registry = registry
        self._agents = dict(agents)
        self._retry_policy = retry_policy or RetryPolicy()

    def execute_run(self, run_id: str, graph: ExecutionGraph) -> OrchestrationResult:
        run = self._repository.get_run(run_id)
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
            payload={"approved": approved, "comment": comment},
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
            payload={"message": "Node execution started.", "attempt": node.retry_count + 1},
        )
        self._repository.save_checkpoint(
            node.run_id,
            self._refresh_state_from_nodes(node.run_id, state),
        )

        output = self._call_agent(running, state)
        for event in output.events:
            self._record_event(
                run_id=node.run_id,
                node_id=node.id,
                event_type=str(event.get("event_type", AgentEventType.LOG)),
                payload={key: value for key, value in event.items() if key != "event_type"},
            )

        if output.status == "succeeded":
            return self._complete_node(running, state, output)
        if output.status == "waiting_for_approval":
            return self._pause_for_approval(running, state, output)
        return self._fail_node(running, state, output)

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
            payload={"message": "Node execution completed.", "summary": output.summary},
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
            payload={"summary": output.summary, "errors": output.errors},
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
                "summary": output.summary,
                "errors": output.errors,
                "retryable": retryable,
                "retry_count": retry_count,
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
        self._repository.add_event(
            AgentEventRecord(
                id=f"event_{uuid4().hex}",
                run_id=run_id,
                node_id=node_id,
                event_type=str(event_type),
                payload=deepcopy(payload),
                created_at=utc_now(),
            )
        )

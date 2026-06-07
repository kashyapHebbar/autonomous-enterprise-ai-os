from __future__ import annotations

from copy import deepcopy
from typing import Any, TypedDict

from aeai_os.agents.base import AgentOutput
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode
from aeai_os.runs.models import RunRecord
from aeai_os.schemas.enums import GraphNodeStatus


class LangGraphRunState(TypedDict):
    run_id: str
    task: str
    plan: list[dict[str, Any]]
    pending_node_ids: list[str]
    completed_node_ids: list[str]
    failed_node_ids: list[str]
    waiting_for_approval_node_id: str | None
    agent_outputs: dict[str, dict[str, Any]]
    artifacts: dict[str, list[str]]
    approvals: dict[str, str]
    evaluation_results: list[dict[str, Any]]
    errors: dict[str, list[str]]


def build_initial_state(run: RunRecord, graph: ExecutionGraph) -> LangGraphRunState:
    return {
        "run_id": run.id,
        "task": run.task,
        "plan": [node_to_plan_item(node) for node in graph.nodes],
        "pending_node_ids": [node.id for node in graph.nodes],
        "completed_node_ids": [],
        "failed_node_ids": [],
        "waiting_for_approval_node_id": None,
        "agent_outputs": {},
        "artifacts": {},
        "approvals": {},
        "evaluation_results": [],
        "errors": {},
    }


def node_to_plan_item(node: ExecutionNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "agent": node.agent,
        "task": node.task,
        "depends_on": list(node.depends_on),
        "required_tools": list(node.required_tools),
        "expected_artifacts": list(node.expected_artifacts),
        "risk": node.risk,
    }


def output_to_state(output: AgentOutput) -> dict[str, Any]:
    return {
        "status": output.status,
        "summary": output.summary,
        "artifacts": list(output.artifacts),
        "events": deepcopy(output.events),
        "metrics": deepcopy(output.metrics),
        "errors": list(output.errors),
    }


def sync_state_from_node_statuses(
    state: LangGraphRunState,
    statuses: dict[str, GraphNodeStatus],
) -> LangGraphRunState:
    synced = deepcopy(state)
    synced["pending_node_ids"] = [
        node_id for node_id, status in statuses.items() if status == GraphNodeStatus.PENDING
    ]
    synced["completed_node_ids"] = [
        node_id for node_id, status in statuses.items() if status == GraphNodeStatus.COMPLETED
    ]
    synced["failed_node_ids"] = [
        node_id for node_id, status in statuses.items() if status == GraphNodeStatus.FAILED
    ]
    waiting_nodes = [
        node_id
        for node_id, status in statuses.items()
        if status == GraphNodeStatus.WAITING_FOR_APPROVAL
    ]
    synced["waiting_for_approval_node_id"] = waiting_nodes[0] if waiting_nodes else None
    return synced

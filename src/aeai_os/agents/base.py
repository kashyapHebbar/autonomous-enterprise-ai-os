from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Protocol


AgentStatus = Literal["succeeded", "failed", "waiting_for_approval"]


@dataclass(frozen=True)
class AgentInput:
    run_id: str
    node_id: str
    task: str
    context: Dict[str, Any] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    approvals: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentOutput:
    status: AgentStatus
    summary: str
    artifacts: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class Agent(Protocol):
    agent_type: str

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        ...


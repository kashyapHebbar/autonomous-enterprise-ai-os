from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

AgentStatus = Literal["succeeded", "failed", "waiting_for_approval"]


@dataclass(frozen=True)
class AgentInput:
    run_id: str
    node_id: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentOutput:
    status: AgentStatus
    summary: str
    artifacts: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Agent(Protocol):
    agent_type: str

    def execute(self, agent_input: AgentInput) -> AgentOutput: ...

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentRegistration:
    agent_type: str
    description: str
    risk_profile: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)


class AgentRegistry:
    def __init__(self, registrations: Iterable[AgentRegistration] | None = None) -> None:
        self._registrations: dict[str, AgentRegistration] = {}
        for registration in registrations or []:
            self.register(registration)

    def register(self, registration: AgentRegistration) -> None:
        if registration.agent_type in self._registrations:
            raise ValueError(f"Agent already registered: {registration.agent_type}")
        self._registrations[registration.agent_type] = registration

    def get(self, agent_type: str) -> AgentRegistration:
        try:
            return self._registrations[agent_type]
        except KeyError as exc:
            raise KeyError(f"Unknown agent type: {agent_type}") from exc

    def list_agent_types(self) -> list[str]:
        return sorted(self._registrations)


def build_default_registry() -> AgentRegistry:
    return AgentRegistry(
        [
            AgentRegistration(
                "planner",
                "Creates the execution graph.",
                "medium",
                ("task_decomposition", "dependency_planning", "execution_graph"),
            ),
            AgentRegistration(
                "security",
                "Applies tool policy and approval gates.",
                "high",
                ("tool_policy", "approval_gates", "risk_assessment"),
            ),
            AgentRegistration(
                "data_retrieval",
                "Profiles and retrieves datasets.",
                "low",
                ("dataset_reference", "schema_profile", "quality_signals"),
            ),
            AgentRegistration(
                "analytics_code",
                "Computes KPIs and reproducible analysis.",
                "medium",
                ("kpi_generation", "analysis_code", "deterministic_metrics"),
            ),
            AgentRegistration(
                "visualization",
                "Creates chart and dashboard artifacts.",
                "low",
                ("chart_rendering", "dashboard_html", "visual_summary"),
            ),
            AgentRegistration(
                "report",
                "Generates final report artifacts.",
                "low",
                ("markdown_report", "executive_summary", "artifact_synthesis"),
            ),
            AgentRegistration(
                "evaluation",
                "Scores outputs for quality and grounding.",
                "low",
                ("quality_checks", "evaluation_records", "grounding_review"),
            ),
            AgentRegistration(
                "deployment",
                "Stores or deploys validated artifacts.",
                "high",
                ("artifact_promotion", "deployment_request", "release_metadata"),
            ),
        ]
    )

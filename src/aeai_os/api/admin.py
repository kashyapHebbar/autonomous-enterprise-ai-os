from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from aeai_os.agents.registry import AgentRegistry
from aeai_os.api.auth import AdminUser
from aeai_os.runs.models import RunRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import GraphNodeStatus, RunStatus
from aeai_os.security import ToolPermissionRegistry


class AgentAdminResponse(BaseModel):
    agent_type: str
    description: str
    risk_profile: str
    capabilities: list[str]
    status: str = "registered"


class PolicyAdminResponse(BaseModel):
    permissions: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    summary: dict[str, int] = Field(default_factory=dict)


class AffectedRunResponse(BaseModel):
    id: str
    task: str
    status: str
    affected_area: str
    reason: str
    connector_id: str | None = None
    policy_rule_id: str | None = None
    updated_at: datetime
    inspector_url: str


def build_admin_router(
    *,
    agent_registry: AgentRegistry,
    policy_registry: ToolPermissionRegistry,
    run_repository: InMemoryRunRepository,
) -> APIRouter:
    router = APIRouter(prefix="/admin", tags=["admin"])

    @router.get("/agents", response_model=list[AgentAdminResponse])
    def list_agents(user: AdminUser) -> list[AgentAdminResponse]:
        return [
            _agent_to_response(agent_registry.get(agent_type))
            for agent_type in agent_registry.list_agent_types()
        ]

    @router.get("/policies", response_model=PolicyAdminResponse)
    def list_policies(user: AdminUser) -> PolicyAdminResponse:
        permissions = [
            permission.model_dump(mode="json")
            for tool in policy_registry.list_tools()
            if (permission := policy_registry.get(tool)) is not None
        ]
        rules = [rule.model_dump(mode="json") for rule in policy_registry.list_rules()]
        return PolicyAdminResponse(
            permissions=permissions,
            rules=rules,
            summary={
                "permissions": len(permissions),
                "rules": len(rules),
                "approval_required": sum(
                    1 for permission in permissions if permission["approval_required"]
                ),
                "blocked": sum(1 for permission in permissions if permission["blocked"]),
            },
        )

    @router.get("/affected-runs", response_model=list[AffectedRunResponse])
    def list_affected_runs(user: AdminUser) -> list[AffectedRunResponse]:
        return _find_affected_runs(
            run_repository,
            organization_id=user.organization_id,
            workspace_id=user.workspace_id,
        )

    return router


def _agent_to_response(registration) -> AgentAdminResponse:
    return AgentAdminResponse(
        agent_type=registration.agent_type,
        description=registration.description,
        risk_profile=registration.risk_profile,
        capabilities=list(registration.capabilities),
    )


def _find_affected_runs(
    repository: InMemoryRunRepository,
    *,
    organization_id: str = "local-org",
    workspace_id: str = "default",
) -> list[AffectedRunResponse]:
    affected: list[AffectedRunResponse] = []
    for run in reversed(repository.list_runs()):
        if run.metadata.get("organization_id", "local-org") != organization_id:
            continue
        if run.metadata.get("workspace_id", "default") != workspace_id:
            continue
        candidate = _affected_run_from_record(repository, run)
        if candidate is not None:
            affected.append(candidate)
        if len(affected) >= 12:
            break
    return affected


def _affected_run_from_record(
    repository: InMemoryRunRepository,
    run: RunRecord,
) -> AffectedRunResponse | None:
    search_parts: list[str] = [
        run.error_summary or "",
        " ".join(f"{key}:{value}" for key, value in run.metadata.items()),
    ]
    connector_id = _string_value(run.metadata.get("connector_id"))
    policy_rule_id = _string_value(run.metadata.get("policy_rule_id"))

    for node in repository.list_graph_nodes(run.id):
        search_parts.extend([node.agent_type, " ".join(node.required_tools)])
        if node.status == GraphNodeStatus.FAILED:
            search_parts.append("failed")

    for event in repository.list_events(run.id):
        search_parts.extend([event.event_type, str(event.payload)])
        connector_id = connector_id or _string_value(event.payload.get("connector_id"))
        policy_rule_id = policy_rule_id or _string_value(event.payload.get("policy_rule_id"))

    haystack = " ".join(search_parts).lower()
    failed_or_waiting = run.status in {
        RunStatus.FAILED,
        RunStatus.WAITING_FOR_APPROVAL,
    }

    if connector_id or (
        failed_or_waiting
        and any(keyword in haystack for keyword in ("connector", "credential", "snowflake"))
    ):
        return AffectedRunResponse(
            id=run.id,
            task=run.task,
            status=run.status.value,
            affected_area="connector",
            reason=run.error_summary or "Connector or credential issue detected.",
            connector_id=connector_id,
            updated_at=run.updated_at,
            inspector_url=f"/run-inspector/runs/{run.id}",
        )

    if policy_rule_id or (
        failed_or_waiting
        and any(
            keyword in haystack
            for keyword in ("policy", "approval", "permission", "blocked", "denied")
        )
    ):
        return AffectedRunResponse(
            id=run.id,
            task=run.task,
            status=run.status.value,
            affected_area="policy",
            reason=run.error_summary or "Policy or approval issue detected.",
            policy_rule_id=policy_rule_id,
            updated_at=run.updated_at,
            inspector_url=f"/run-inspector/runs/{run.id}",
        )

    return None


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

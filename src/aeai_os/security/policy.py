from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolPermissionLevel(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    EXTERNAL_NETWORK = "external_network"
    CODE_EXECUTION = "code_execution"
    DEPLOYMENT = "deployment"


class ToolRiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ToolPolicyDecisionStatus(StrEnum):
    ALLOW = "allow"
    APPROVAL_REQUIRED = "approval_required"
    BLOCK = "block"


class ToolPermission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str = Field(..., min_length=1, max_length=128)
    permission_level: ToolPermissionLevel
    risk: ToolRiskLevel
    description: str = Field(..., min_length=1, max_length=500)
    approval_required: bool = False
    blocked: bool = False
    destructive: bool = False

    @field_validator("tool", "description")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value must not be blank.")
        return normalized


class ToolPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: str
    permission_level: ToolPermissionLevel | None
    risk: ToolRiskLevel
    decision: ToolPolicyDecisionStatus
    reason: str
    input_summary: str
    approval_required: bool = False
    approved: bool = False
    destructive: bool = False


class ToolPermissionRegistry:
    def __init__(self, permissions: Iterable[ToolPermission] | None = None) -> None:
        self._permissions: dict[str, ToolPermission] = {}
        for permission in permissions or []:
            self.register(permission)

    def register(self, permission: ToolPermission) -> None:
        if permission.tool in self._permissions:
            raise ValueError(f"Tool permission already registered: {permission.tool}")
        self._permissions[permission.tool] = permission

    def get(self, tool: str) -> ToolPermission | None:
        return self._permissions.get(tool)

    def list_tools(self) -> list[str]:
        return sorted(self._permissions)

    def evaluate(
        self,
        tool: str,
        *,
        input_summary: str,
        approved: bool = False,
    ) -> ToolPolicyDecision:
        permission = self.get(tool)
        if permission is None:
            return ToolPolicyDecision(
                tool=tool,
                permission_level=None,
                risk=ToolRiskLevel.HIGH,
                decision=ToolPolicyDecisionStatus.BLOCK,
                reason="Tool is not registered in the permission registry.",
                input_summary=input_summary,
            )

        if permission.blocked:
            return ToolPolicyDecision(
                tool=tool,
                permission_level=permission.permission_level,
                risk=permission.risk,
                decision=ToolPolicyDecisionStatus.BLOCK,
                reason=(
                    "Tool is blocked by policy because it is destructive."
                    if permission.destructive
                    else "Tool is blocked by policy."
                ),
                input_summary=input_summary,
                destructive=permission.destructive,
            )

        requires_approval = permission.approval_required or permission.risk == ToolRiskLevel.HIGH
        if requires_approval and not approved:
            return ToolPolicyDecision(
                tool=tool,
                permission_level=permission.permission_level,
                risk=permission.risk,
                decision=ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
                reason="Tool requires approval before execution.",
                input_summary=input_summary,
                approval_required=True,
                destructive=permission.destructive,
            )

        return ToolPolicyDecision(
            tool=tool,
            permission_level=permission.permission_level,
            risk=permission.risk,
            decision=ToolPolicyDecisionStatus.ALLOW,
            reason=(
                "Tool execution approved." if approved and requires_approval else "Tool allowed."
            ),
            input_summary=input_summary,
            approval_required=requires_approval,
            approved=approved and requires_approval,
            destructive=permission.destructive,
        )


def default_tool_permission_registry() -> ToolPermissionRegistry:
    return ToolPermissionRegistry(
        [
            _permission(
                "dataset_reader",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Read local dataset artifacts.",
            ),
            _permission(
                "schema_profiler",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Infer schema metadata from datasets.",
            ),
            _permission(
                "quality_checker",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Compute dataset quality signals.",
            ),
            _permission(
                "dataframe_query",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Read and aggregate dataset rows.",
            ),
            _permission(
                "artifact_reader",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Read previously registered artifacts.",
            ),
            _permission(
                "deterministic_evaluator",
                ToolPermissionLevel.READ_ONLY,
                ToolRiskLevel.LOW,
                "Run deterministic evaluation checks.",
            ),
            _permission(
                "python_analysis",
                ToolPermissionLevel.CODE_EXECUTION,
                ToolRiskLevel.MEDIUM,
                "Accept statically validated analysis code artifacts.",
            ),
            _permission(
                "code_artifact_writer",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.MEDIUM,
                "Write reproducible analysis code artifacts.",
            ),
            _permission(
                "chart_renderer",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.MEDIUM,
                "Write chart artifacts.",
            ),
            _permission(
                "dashboard_renderer",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.MEDIUM,
                "Write dashboard artifacts.",
            ),
            _permission(
                "markdown_report_writer",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.MEDIUM,
                "Write Markdown report artifacts.",
            ),
            _permission(
                "evaluation_writer",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.MEDIUM,
                "Write evaluation artifacts and records.",
            ),
            _permission(
                "external_http",
                ToolPermissionLevel.EXTERNAL_NETWORK,
                ToolRiskLevel.HIGH,
                "Call external HTTP services.",
                approval_required=True,
            ),
            _permission(
                "snowflake_query",
                ToolPermissionLevel.EXTERNAL_NETWORK,
                ToolRiskLevel.HIGH,
                "Query an external Snowflake warehouse.",
                approval_required=True,
            ),
            _permission(
                "deploy_artifact",
                ToolPermissionLevel.DEPLOYMENT,
                ToolRiskLevel.HIGH,
                "Deploy generated artifacts outside the local sandbox.",
                approval_required=True,
            ),
            _permission(
                "delete_artifact",
                ToolPermissionLevel.WRITE,
                ToolRiskLevel.HIGH,
                "Delete artifacts from storage.",
                blocked=True,
                destructive=True,
            ),
            _permission(
                "shell_exec",
                ToolPermissionLevel.CODE_EXECUTION,
                ToolRiskLevel.HIGH,
                "Execute arbitrary shell commands.",
                blocked=True,
                destructive=True,
            ),
        ]
    )


def _permission(
    tool: str,
    permission_level: ToolPermissionLevel,
    risk: ToolRiskLevel,
    description: str,
    *,
    approval_required: bool = False,
    blocked: bool = False,
    destructive: bool = False,
) -> ToolPermission:
    return ToolPermission(
        tool=tool,
        permission_level=permission_level,
        risk=risk,
        description=description,
        approval_required=approval_required,
        blocked=blocked,
        destructive=destructive,
    )

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any

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
    RETRY = "retry"
    ESCALATE = "escalate"


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
    policy_rule_id: str | None = None
    permission_level: ToolPermissionLevel | None
    risk: ToolRiskLevel
    decision: ToolPolicyDecisionStatus
    reason: str
    input_summary: str
    approval_required: bool = False
    approved: bool = False
    destructive: bool = False
    escalation_target: str | None = None
    retry_after_seconds: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class PolicyEvaluationContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_summary: str = Field(..., min_length=1, max_length=1000)
    approved: bool = False
    agent_type: str | None = None
    node_id: str | None = None
    run_id: str | None = None
    connector_id: str | None = None
    credential_profile_id: str | None = None
    artifact_type: str | None = None
    artifact_sensitive: bool = False
    destination: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_summary")
    @classmethod
    def normalize_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy input summary must not be blank.")
        return normalized


class PolicyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=128)
    description: str = Field(..., min_length=1, max_length=500)
    decision: ToolPolicyDecisionStatus
    reason: str = Field(..., min_length=1, max_length=500)
    tool_patterns: list[str] = Field(default_factory=lambda: ["*"])
    permission_levels: list[ToolPermissionLevel] = Field(default_factory=list)
    risk_levels: list[ToolRiskLevel] = Field(default_factory=list)
    connector_ids: list[str] = Field(default_factory=list)
    artifact_types: list[str] = Field(default_factory=list)
    destinations: list[str] = Field(default_factory=list)
    sensitive_artifact: bool | None = None
    metadata_keys: list[str] = Field(default_factory=list)
    escalation_target: str | None = Field(default=None, max_length=200)
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86400)

    @field_validator("id", "description", "reason")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Policy rule value must not be blank.")
        return normalized

    @field_validator(
        "tool_patterns",
        "connector_ids",
        "artifact_types",
        "destinations",
        "metadata_keys",
    )
    @classmethod
    def normalize_list(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text and text not in normalized:
                normalized.append(text)
        return normalized


class ToolPermissionRegistry:
    def __init__(
        self,
        permissions: Iterable[ToolPermission] | None = None,
        rules: Iterable[PolicyRule] | None = None,
    ) -> None:
        self._permissions: dict[str, ToolPermission] = {}
        for permission in permissions or []:
            self.register(permission)
        self._rules: dict[str, PolicyRule] = {}
        for rule in rules or []:
            self.register_rule(rule)

    def register(self, permission: ToolPermission) -> None:
        if permission.tool in self._permissions:
            raise ValueError(f"Tool permission already registered: {permission.tool}")
        self._permissions[permission.tool] = permission

    def register_rule(self, rule: PolicyRule) -> None:
        if rule.id in self._rules:
            raise ValueError(f"Policy rule already registered: {rule.id}")
        self._rules[rule.id] = rule

    def get(self, tool: str) -> ToolPermission | None:
        return self._permissions.get(tool)

    def list_tools(self) -> list[str]:
        return sorted(self._permissions)

    def list_rules(self) -> list[PolicyRule]:
        return [self._rules[rule_id] for rule_id in sorted(self._rules)]

    def evaluate(
        self,
        tool: str,
        *,
        input_summary: str,
        approved: bool = False,
        context: PolicyEvaluationContext | dict[str, Any] | None = None,
    ) -> ToolPolicyDecision:
        evaluation_context = _build_context(
            input_summary=input_summary,
            approved=approved,
            context=context,
        )
        permission = self.get(tool)
        if permission is None:
            return ToolPolicyDecision(
                tool=tool,
                permission_level=None,
                risk=ToolRiskLevel.HIGH,
                decision=ToolPolicyDecisionStatus.BLOCK,
                reason="Tool is not registered in the permission registry.",
                input_summary=evaluation_context.input_summary,
                context=evaluation_context.model_dump(exclude_none=True),
            )

        matched_rule = _highest_priority_rule(
            self._matching_rules(tool, permission, evaluation_context)
        )
        if matched_rule is not None:
            return _decision_from_rule(
                tool=tool,
                permission=permission,
                rule=matched_rule,
                context=evaluation_context,
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
                input_summary=evaluation_context.input_summary,
                destructive=permission.destructive,
                context=evaluation_context.model_dump(exclude_none=True),
            )

        requires_approval = permission.approval_required or permission.risk == ToolRiskLevel.HIGH
        if requires_approval and not approved:
            return ToolPolicyDecision(
                tool=tool,
                permission_level=permission.permission_level,
                risk=permission.risk,
                decision=ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
                reason="Tool requires approval before execution.",
                input_summary=evaluation_context.input_summary,
                approval_required=True,
                destructive=permission.destructive,
                context=evaluation_context.model_dump(exclude_none=True),
            )

        return ToolPolicyDecision(
            tool=tool,
            permission_level=permission.permission_level,
            risk=permission.risk,
            decision=ToolPolicyDecisionStatus.ALLOW,
            reason=(
                "Tool execution approved." if approved and requires_approval else "Tool allowed."
            ),
            input_summary=evaluation_context.input_summary,
            approval_required=requires_approval,
            approved=approved and requires_approval,
            destructive=permission.destructive,
            context=evaluation_context.model_dump(exclude_none=True),
        )

    def _matching_rules(
        self,
        tool: str,
        permission: ToolPermission,
        context: PolicyEvaluationContext,
    ) -> list[PolicyRule]:
        return [
            rule
            for rule in self._rules.values()
            if _rule_matches(
                rule=rule,
                tool=tool,
                permission=permission,
                context=context,
            )
        ]


def default_tool_permission_registry() -> ToolPermissionRegistry:
    return ToolPermissionRegistry(
        permissions=[
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
        ],
        rules=[
            PolicyRule(
                id="code-execution-approval",
                description="Gate untrusted code execution tools before they can affect outputs.",
                decision=ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
                reason="Untrusted code execution requires reviewer approval.",
                tool_patterns=["untrusted_*", "dynamic_python_exec"],
            ),
            PolicyRule(
                id="deployment-promotion-approval",
                description="Gate deployment promotion outside local artifact storage.",
                decision=ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
                reason="Deployment promotion requires release approval.",
                permission_levels=[ToolPermissionLevel.DEPLOYMENT],
            ),
            PolicyRule(
                id="external-connector-escalation",
                description="Escalate external connector access to platform security.",
                decision=ToolPolicyDecisionStatus.ESCALATE,
                reason="External connector access requires platform-security review.",
                permission_levels=[ToolPermissionLevel.EXTERNAL_NETWORK],
                escalation_target="platform-security",
            ),
            PolicyRule(
                id="sensitive-artifact-approval",
                description=(
                    "Gate access to artifacts marked sensitive or containing "
                    "secret-like metadata."
                ),
                decision=ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
                reason="Sensitive artifact access requires approval.",
                tool_patterns=["artifact_reader", "dataset_reader"],
                sensitive_artifact=True,
                metadata_keys=["pii", "contains_pii", "sensitive", "secret"],
            ),
            PolicyRule(
                id="destructive-action-deny",
                description="Deny destructive tool use.",
                decision=ToolPolicyDecisionStatus.BLOCK,
                reason="Destructive tool use is denied by governance policy.",
                tool_patterns=["delete_*", "shell_exec"],
            ),
        ],
    )


def build_policy_registry_from_rules(
    rules: Iterable[PolicyRule | dict[str, Any]],
    permissions: Iterable[ToolPermission] | None = None,
) -> ToolPermissionRegistry:
    parsed_rules = [
        rule if isinstance(rule, PolicyRule) else PolicyRule.model_validate(rule)
        for rule in rules
    ]
    base = (
        default_tool_permission_registry()
        if permissions is None
        else ToolPermissionRegistry(permissions)
    )
    for rule in parsed_rules:
        base.register_rule(rule)
    return base


def _build_context(
    *,
    input_summary: str,
    approved: bool,
    context: PolicyEvaluationContext | dict[str, Any] | None,
) -> PolicyEvaluationContext:
    if isinstance(context, PolicyEvaluationContext):
        payload = context.model_dump()
    else:
        payload = dict(context or {})
    payload.setdefault("input_summary", input_summary)
    payload.setdefault("approved", approved)
    return PolicyEvaluationContext.model_validate(payload)


def _highest_priority_rule(rules: list[PolicyRule]) -> PolicyRule | None:
    if not rules:
        return None
    priority = {
        ToolPolicyDecisionStatus.BLOCK: 0,
        ToolPolicyDecisionStatus.RETRY: 1,
        ToolPolicyDecisionStatus.ESCALATE: 2,
        ToolPolicyDecisionStatus.APPROVAL_REQUIRED: 3,
        ToolPolicyDecisionStatus.ALLOW: 4,
    }
    return sorted(rules, key=lambda rule: (priority[rule.decision], rule.id))[0]


def _decision_from_rule(
    *,
    tool: str,
    permission: ToolPermission,
    rule: PolicyRule,
    context: PolicyEvaluationContext,
) -> ToolPolicyDecision:
    requires_approval = rule.decision in {
        ToolPolicyDecisionStatus.APPROVAL_REQUIRED,
        ToolPolicyDecisionStatus.ESCALATE,
    }
    if requires_approval and context.approved:
        return ToolPolicyDecision(
            tool=tool,
            policy_rule_id=rule.id,
            permission_level=permission.permission_level,
            risk=permission.risk,
            decision=ToolPolicyDecisionStatus.ALLOW,
            reason=f"{rule.reason} Approval has been granted.",
            input_summary=context.input_summary,
            approval_required=True,
            approved=True,
            destructive=permission.destructive,
            escalation_target=rule.escalation_target,
            context=context.model_dump(exclude_none=True),
        )
    return ToolPolicyDecision(
        tool=tool,
        policy_rule_id=rule.id,
        permission_level=permission.permission_level,
        risk=permission.risk,
        decision=rule.decision,
        reason=rule.reason,
        input_summary=context.input_summary,
        approval_required=requires_approval,
        destructive=permission.destructive,
        escalation_target=rule.escalation_target,
        retry_after_seconds=rule.retry_after_seconds,
        context=context.model_dump(exclude_none=True),
    )


def _rule_matches(
    *,
    rule: PolicyRule,
    tool: str,
    permission: ToolPermission,
    context: PolicyEvaluationContext,
) -> bool:
    if rule.tool_patterns and not any(fnmatch(tool, pattern) for pattern in rule.tool_patterns):
        return False
    if rule.permission_levels and permission.permission_level not in rule.permission_levels:
        return False
    if rule.risk_levels and permission.risk not in rule.risk_levels:
        return False
    if rule.connector_ids and context.connector_id not in rule.connector_ids:
        return False
    if rule.artifact_types and context.artifact_type not in rule.artifact_types:
        return False
    if rule.destinations and not _matches_any(context.destination or "", rule.destinations):
        return False
    if (
        rule.sensitive_artifact is not None
        and context.artifact_sensitive != rule.sensitive_artifact
    ):
        if not _metadata_has_any_key(context.metadata, rule.metadata_keys):
            return False
    elif rule.metadata_keys and not _metadata_has_any_key(context.metadata, rule.metadata_keys):
        return False
    return True


def _matches_any(value: str, patterns: list[str]) -> bool:
    return any(fnmatch(value, pattern) for pattern in patterns)


def _metadata_has_any_key(metadata: dict[str, Any], keys: list[str]) -> bool:
    if not keys:
        return False
    normalized_keys = {key.lower() for key in keys}
    return any(str(key).lower() in normalized_keys for key in metadata)


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

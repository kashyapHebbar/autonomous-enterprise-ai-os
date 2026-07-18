from __future__ import annotations

from aeai_os.security import (
    PolicyEvaluationContext,
    PolicyRule,
    ToolPermission,
    ToolPermissionLevel,
    ToolPermissionRegistry,
    ToolPolicyDecisionStatus,
    ToolRiskLevel,
    default_tool_permission_registry,
)


def test_default_tool_policy_classifies_read_only_tool_as_allowed():
    registry = default_tool_permission_registry()

    decision = registry.evaluate("dataset_reader", input_summary="read dataset")

    assert decision.decision == ToolPolicyDecisionStatus.ALLOW
    assert decision.permission_level == ToolPermissionLevel.READ_ONLY
    assert decision.risk == ToolRiskLevel.LOW


def test_default_tool_policy_requires_approval_for_external_network_tool():
    registry = default_tool_permission_registry()

    pending = registry.evaluate("external_http", input_summary="call external API")
    approved = registry.evaluate(
        "external_http",
        input_summary="call external API",
        approved=True,
    )

    assert pending.decision == ToolPolicyDecisionStatus.ESCALATE
    assert pending.policy_rule_id == "external-connector-escalation"
    assert pending.escalation_target == "platform-security"
    assert pending.permission_level == ToolPermissionLevel.EXTERNAL_NETWORK
    assert pending.risk == ToolRiskLevel.HIGH
    assert approved.decision == ToolPolicyDecisionStatus.ALLOW
    assert approved.approved is True


def test_default_tool_policy_blocks_destructive_tool():
    registry = default_tool_permission_registry()

    decision = registry.evaluate("shell_exec", input_summary="run shell")

    assert decision.decision == ToolPolicyDecisionStatus.BLOCK
    assert decision.permission_level == ToolPermissionLevel.CODE_EXECUTION
    assert decision.destructive is True


def test_default_tool_policy_blocks_unknown_tool():
    registry = default_tool_permission_registry()

    decision = registry.evaluate("unregistered_tool", input_summary="unknown")

    assert decision.decision == ToolPolicyDecisionStatus.BLOCK
    assert decision.permission_level is None
    assert "not registered" in decision.reason


def test_policy_rule_can_gate_sensitive_artifact_access():
    registry = default_tool_permission_registry()

    pending = registry.evaluate(
        "artifact_reader",
        input_summary="read generated report",
        context=PolicyEvaluationContext(
            input_summary="read generated report",
            artifact_type="report",
            artifact_sensitive=True,
            metadata={"sensitive": True},
        ),
    )
    approved = registry.evaluate(
        "artifact_reader",
        input_summary="read generated report",
        approved=True,
        context=PolicyEvaluationContext(
            input_summary="read generated report",
            approved=True,
            artifact_type="report",
            artifact_sensitive=True,
            metadata={"sensitive": True},
        ),
    )

    assert pending.decision == ToolPolicyDecisionStatus.APPROVAL_REQUIRED
    assert pending.policy_rule_id == "sensitive-artifact-approval"
    assert approved.decision == ToolPolicyDecisionStatus.ALLOW
    assert approved.approved is True


def test_custom_policy_rule_can_request_retry():
    registry = ToolPermissionRegistry(
        permissions=[
            ToolPermission(
                tool="snowflake_query",
                permission_level=ToolPermissionLevel.EXTERNAL_NETWORK,
                risk=ToolRiskLevel.HIGH,
                description="Query Snowflake.",
            )
        ],
        rules=[
            PolicyRule(
                id="retry-snowflake-maintenance",
                description="Retry Snowflake access during maintenance windows.",
                decision=ToolPolicyDecisionStatus.RETRY,
                reason="Connector is temporarily unavailable.",
                tool_patterns=["snowflake_query"],
                retry_after_seconds=60,
            )
        ],
    )

    decision = registry.evaluate("snowflake_query", input_summary="query procurement table")

    assert decision.decision == ToolPolicyDecisionStatus.RETRY
    assert decision.policy_rule_id == "retry-snowflake-maintenance"
    assert decision.retry_after_seconds == 60

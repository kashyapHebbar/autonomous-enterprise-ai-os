from __future__ import annotations

from aeai_os.security import (
    ToolPermissionLevel,
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

    assert pending.decision == ToolPolicyDecisionStatus.APPROVAL_REQUIRED
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

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum


class CodeSafetyDecision(StrEnum):
    SAFE = "safe"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CodePolicyViolation:
    rule: str
    message: str
    line: int | None = None


@dataclass(frozen=True)
class CodeSafetyReport:
    decision: CodeSafetyDecision
    violations: list[CodePolicyViolation]

    @property
    def safe(self) -> bool:
        return self.decision == CodeSafetyDecision.SAFE

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "violations": [
                {
                    "rule": violation.rule,
                    "message": violation.message,
                    "line": violation.line,
                }
                for violation in self.violations
            ],
        }


class PythonCodeGuard:
    """Static policy for generated analysis code; it never executes the source."""

    _allowed_imports = {
        "argparse",
        "collections",
        "csv",
        "json",
        "math",
        "statistics",
    }
    _blocked_calls = {
        "__import__",
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "setattr",
        "vars",
    }
    _blocked_attributes = {
        "connect",
        "popen",
        "remove",
        "request",
        "rmdir",
        "rmtree",
        "spawn",
        "system",
        "unlink",
        "urlopen",
    }
    _approval_attributes = {
        "chmod",
        "mkdir",
        "rename",
        "write",
        "write_bytes",
        "write_text",
    }

    def evaluate(self, source: str) -> CodeSafetyReport:
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            return CodeSafetyReport(
                decision=CodeSafetyDecision.BLOCKED,
                violations=[
                    CodePolicyViolation(
                        rule="syntax_error",
                        message=exc.msg,
                        line=exc.lineno,
                    )
                ],
            )

        blocked: list[CodePolicyViolation] = []
        approval_required: list[CodePolicyViolation] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._check_import(node, blocked)
            elif isinstance(node, ast.Call):
                self._check_call(node, blocked, approval_required)
            elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                blocked.append(
                    CodePolicyViolation(
                        rule="dunder_access",
                        message=f"Dunder attribute access is blocked: {node.attr}",
                        line=node.lineno,
                    )
                )

        if blocked:
            return CodeSafetyReport(CodeSafetyDecision.BLOCKED, _deduplicate(blocked))
        if approval_required:
            return CodeSafetyReport(
                CodeSafetyDecision.APPROVAL_REQUIRED,
                _deduplicate(approval_required),
            )
        return CodeSafetyReport(CodeSafetyDecision.SAFE, [])

    def _check_import(
        self,
        node: ast.Import | ast.ImportFrom,
        blocked: list[CodePolicyViolation],
    ) -> None:
        modules = (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
        )
        for module in modules:
            root = module.split(".", maxsplit=1)[0]
            if root not in self._allowed_imports:
                blocked.append(
                    CodePolicyViolation(
                        rule="blocked_import",
                        message=f"Import is not allowed in analysis code: {module}",
                        line=node.lineno,
                    )
                )

    def _check_call(
        self,
        node: ast.Call,
        blocked: list[CodePolicyViolation],
        approval_required: list[CodePolicyViolation],
    ) -> None:
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name in self._blocked_calls:
                blocked.append(
                    CodePolicyViolation(
                        rule="blocked_call",
                        message=f"Dynamic or interactive call is blocked: {name}",
                        line=node.lineno,
                    )
                )
            elif name == "open" and _open_requires_approval(node):
                approval_required.append(
                    CodePolicyViolation(
                        rule="filesystem_write",
                        message="Opening files for write access requires approval.",
                        line=node.lineno,
                    )
                )
            return

        if not isinstance(node.func, ast.Attribute):
            return
        attribute = node.func.attr
        if attribute in self._blocked_attributes:
            blocked.append(
                CodePolicyViolation(
                    rule="blocked_operation",
                    message=f"Unsafe operation is blocked: {attribute}",
                    line=node.lineno,
                )
            )
        elif attribute in self._approval_attributes:
            approval_required.append(
                CodePolicyViolation(
                    rule="approval_required",
                    message=f"Operation requires approval: {attribute}",
                    line=node.lineno,
                )
            )
        elif attribute == "open" and _open_requires_approval(node):
            approval_required.append(
                CodePolicyViolation(
                    rule="filesystem_write",
                    message="Opening files for write access requires approval.",
                    line=node.lineno,
                )
            )


def _open_requires_approval(node: ast.Call) -> bool:
    mode_node: ast.expr | None = None
    if len(node.args) >= 2:
        mode_node = node.args[1]
    for keyword in node.keywords:
        if keyword.arg == "mode":
            mode_node = keyword.value
            break
    if mode_node is None:
        return False
    if not isinstance(mode_node, ast.Constant) or not isinstance(mode_node.value, str):
        return True
    return any(flag in mode_node.value for flag in "wax+")


def _deduplicate(violations: list[CodePolicyViolation]) -> list[CodePolicyViolation]:
    unique: list[CodePolicyViolation] = []
    seen: set[tuple[str, str, int | None]] = set()
    for violation in violations:
        key = (violation.rule, violation.message, violation.line)
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return unique

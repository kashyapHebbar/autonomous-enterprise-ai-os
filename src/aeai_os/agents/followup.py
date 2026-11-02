"""Upgrade 8: one bounded, evidence-grounded follow-up decision.

No arbitrary tool arguments or executable code. Only an approved check ID can be
chosen and each result is computed by the existing read-only analysis engine.
"""

from __future__ import annotations

import json
from typing import Any

FOLLOWUP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "decision": {"type": "string", "enum": ["stop", "continue"]},
        "checks": {"type": "array", "items": {"type": "string"}},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["decision", "checks", "evidence_ids", "question", "rationale"],
}


def followup_context(
    task: str,
    steps: list[dict[str, Any]],
    remaining: list[str],
    max_checks: int,
) -> str:
    """Only aggregate evidence and the approved capability names leave the host."""
    facts = [
        {"evidence_id": step["evidence_id"], "check": step["check"], "facts": step["facts"]}
        for step in steps[:3]
    ]
    return json.dumps(
        {
            "business_question": task[:850],
            "verified_initial_evidence": facts,
            "available_additional_checks": remaining,
            "max_additional_checks": max_checks,
            "decision_rule": "Only continue if the verified evidence leaves a concrete, answerable gap.",  # noqa: E501
        },
        ensure_ascii=False,
    )[:6500]


def validate_followup(
    response: dict[str, Any],
    *,
    remaining: list[str],
    evidence_ids: set[str],
    max_checks: int,
) -> dict[str, Any]:
    if not isinstance(response, dict) or set(response) != {
        "decision",
        "checks",
        "evidence_ids",
        "question",
        "rationale",
    }:
        raise ValueError("Follow-up response fields are invalid.")
    decision = response["decision"]
    if decision not in {"stop", "continue"}:
        raise ValueError("Follow-up decision must be stop or continue.")
    question = response["question"]
    rationale = response["rationale"]
    if not all(isinstance(x, str) and len(x) <= 320 for x in (question, rationale)):
        raise ValueError("Follow-up question and rationale must be bounded text.")
    raw_checks = response["checks"]
    ids = response["evidence_ids"]
    if not isinstance(raw_checks, list) or len(raw_checks) > 24:
        raise ValueError("Follow-up checks are not a bounded list.")
    if not isinstance(ids, list) or len(ids) > 12:
        raise ValueError("Follow-up evidence IDs are not a bounded list.")
    if any(not isinstance(x, str) or x not in remaining for x in raw_checks):
        raise ValueError("Follow-up requested an unknown, duplicate or unapproved check.")
    if any(not isinstance(x, str) or x not in evidence_ids for x in ids):
        raise ValueError("Follow-up cited unknown evidence.")
    checks = list(dict.fromkeys(raw_checks))
    cited = list(dict.fromkeys(ids))
    if decision == "stop":
        if checks:
            raise ValueError("A stop decision may not request checks.")
        return {
            "decision": "stop",
            "checks": [],
            "evidence_ids": cited,
            "question": question,
            "rationale": rationale,
        }
    if not 1 <= len(checks) <= max_checks or not cited or not question.strip():
        raise ValueError("Continuing requires an evidence-grounded question and bounded checks.")
    return {
        "decision": "continue",
        "checks": checks,
        "evidence_ids": cited,
        "question": question,
        "rationale": rationale,
    }

"""Upgrade 8 offline tests. All HF model calls are mocked; no token required."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.followup import followup_context, validate_followup
from aeai_os.api.app import create_app
from aeai_os.llm.gateway import LLMError
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import get_settings

RESPONSE = {
    "decision": "continue",
    "checks": ["monthly_trend", "savings_review"],
    "evidence_ids": ["check_1", "check_2"],
    "question": "Do the verified anomalies coincide with unusual spending trends?",
    "rationale": "Existing evidence suggests the time pattern deserves a separate check.",
}


def validate(payload: dict, *, allowed=None, limit=2):
    return validate_followup(
        payload,
        remaining=allowed if allowed is not None else ["monthly_trend", "savings_review"],
        evidence_ids={"check_1", "check_2", "check_3"},
        max_checks=limit,
    )


def test_settings_opt_in_and_defaults(monkeypatch):
    monkeypatch.delenv("AEAI_REASONING_FOLLOWUPS_ENABLED", raising=False)
    assert get_settings().reasoning_followups_enabled is False
    assert get_settings().reasoning_max_followup_checks == 2
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "true")
    monkeypatch.setenv("AEAI_REASONING_MAX_FOLLOWUP_CHECKS", "1")
    assert get_settings().reasoning_followups_enabled
    assert get_settings().reasoning_max_followup_checks == 1


def test_one_bounded_evidence_cited_followup():
    result = validate(RESPONSE)
    assert result["decision"] == "continue"
    assert result["checks"] == ["monthly_trend", "savings_review"]
    assert validate({**RESPONSE, "checks": ["monthly_trend"] * 6})["checks"] == ["monthly_trend"]
    assert (
        validate({**RESPONSE, "decision": "stop", "checks": [], "evidence_ids": []})["decision"]
        == "stop"
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"checks": ["shell_exec"]},
        {"checks": ["dataset_overview"]},
        {
            "checks": ["monthly_trend", "monthly_trend", "savings_review"],
            "evidence_ids": ["unknown"],
        },
        {"evidence_ids": ["check_999"]},
        {"evidence_ids": []},
        {"checks": []},
        {"question": ""},
        {"decision": "run_arbitrary_python"},
        {"decision": "stop", "checks": ["monthly_trend"]},
        {"rationale": "x" * 321},
        {"checks": "monthly_trend"},
        {"checks": ["monthly_trend"] * 25},
        {"extra_key": "execute"},
    ],
)
def test_malicious_or_inconsistent_followup_rejected(patch):
    with pytest.raises(ValueError):
        validate({**RESPONSE, **patch})


def test_check_ceiling_strictly_enforced():
    with pytest.raises(ValueError):
        validate(RESPONSE, limit=1)
    assert validate({**RESPONSE, "checks": ["savings_review"]}, limit=1)["checks"] == [
        "savings_review"
    ]


def test_followup_context_only_has_approved_aggregates():
    steps = [
        {
            "check": "anomaly_triage",
            "evidence_id": "check_1",
            "facts": {"anomaly_count": 10},
            "source_paths": ["private/backend/location"],
            "raw_transactions": ["SECRET PRIVATE ROW"],
        }
    ]
    context = followup_context("Check spend", steps, ["monthly_trend"], 1)
    parsed = json.loads(context)
    assert parsed["verified_initial_evidence"][0]["facts"] == {"anomaly_count": 10}
    assert "SECRET PRIVATE ROW" not in context
    assert "private/backend/location" not in context
    assert parsed["available_additional_checks"] == ["monthly_trend"]


class MockQwen:
    model = "Qwen/Qwen3-32B"

    def __init__(self, decision="continue", fail=False, unapproved=False):
        self.requests = []
        self.decision = decision
        self.fail = fail
        self.unapproved = unapproved

    def generate(self, **request):
        self.requests.append(request)
        name = request["schema_name"]
        if name == "enterprise_analysis_recommendation":
            return {
                "recipe": "procurement",
                "goals": ["summary", "trend"],
                "rationale": "Appropriate procurement analysis",
            }
        if name == "enterprise_investigation_checks":
            return {
                "checks": ["anomaly_triage", "supplier_concentration", "data_quality"],
                "focus": "Investigate procurement risks",
                "rationale": "Evidence-first.",
            }
        if name == "enterprise_investigation_followup":
            if self.fail:
                raise LLMError("Offline provider outage")
            if self.unapproved:
                return {**RESPONSE, "checks": ["run_shell_command"]}
            if self.decision == "stop":
                return {**RESPONSE, "decision": "stop", "checks": [], "evidence_ids": ["check_1"]}
            return RESPONSE
        if name == "enterprise_ai_briefing":
            return {
                "headline": "Procurement overview",
                "executive_summary": "Validate unusual activity.",
                "observations": ["Supplier concentration may warrant review."],
                "limitations": ["Review the source transactions."],
            }
        raise AssertionError(f"Unexpected schema: {name}")


def run_workflow(
    monkeypatch,
    tmp_path,
    *,
    enabled=True,
    decision="continue",
    fail=False,
    unapproved=False,
    max_calls=4,
):
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "true")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "true")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", str(enabled).lower())
    monkeypatch.setenv("AEAI_REASONING_REVIEW_ENABLED", "false")
    monkeypatch.setenv("AEAI_LLM_MAX_CALLS_PER_RUN", str(max_calls))
    monkeypatch.setenv("AEAI_LLM_USAGE_LEDGER_PATH", str(tmp_path / "usage.jsonl"))
    mock = MockQwen(decision=decision, fail=fail, unapproved=unapproved)
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **_: mock)
    monkeypatch.setattr("aeai_os.agents.investigation.build_llm_gateway", lambda **_: mock)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **_: mock)
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "outputs"))
    run = client.post(
        "/runs",
        json={
            "task": "Investigate supplier risks and monthly spend anomalies",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    result = client.post(f"/runs/{run['id']}/execute")
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["status"] == "completed"
    assert payload["evaluations"][0]["passed"] is True
    evidence = next(
        a for a in payload["artifacts"] if a["metadata"].get("edition") == "investigation_evidence"
    )
    investigation = client.get(f"/runs/{run['id']}/artifacts/{evidence['id']}/content").json()
    return payload, investigation, mock, repo, run


def test_followup_expands_into_new_verified_checks_with_lineage(monkeypatch, tmp_path):
    run_result, evidence, mock, repo, run = run_workflow(monkeypatch, tmp_path)
    assert evidence["followup"]["status"] == "expanded"
    assert evidence["followup"]["checks"] == ["monthly_trend", "savings_review"]
    assert [s["check"] for s in evidence["steps"]] == [
        "anomaly_triage",
        "supplier_concentration",
        "data_quality",
        "monthly_trend",
        "savings_review",
    ]
    assert [s["evidence_id"] for s in evidence["steps"]] == [
        "check_1",
        "check_2",
        "check_3",
        "check_4",
        "check_5",
    ]
    assert [s["phase"] for s in evidence["steps"][-2:]] == ["followup", "followup"]
    assert evidence["steps"][-1]["based_on_evidence_ids"] == ["check_1", "check_2"]
    assert all(s["status"] == "verified_from_computed_artifacts" for s in evidence["steps"])
    assert (
        next(a for a in run_result["artifacts"] if a["type"] == "kpi_table")["metadata"][
            "total_spend"
        ]
        == 165962.5
    )
    assert [c["schema_name"] for c in mock.requests] == [
        "enterprise_analysis_recommendation",
        "enterprise_investigation_checks",
        "enterprise_investigation_followup",
        "enterprise_ai_briefing",
    ]
    events = repo.list_events(run["id"])
    assert any(
        e.node_id == "investigation" and e.payload.get("followup_status") == "expanded"
        for e in events
    )
    tool_calls = [
        e
        for e in events
        if e.node_id == "investigation" and e.event_type == "tool_call" and "phase" in e.payload
    ]
    assert len(tool_calls) == 5
    assert len([e for e in tool_calls if e.payload.get("phase") == "followup"]) == 2


def test_followup_can_stop_without_new_checks(monkeypatch, tmp_path):
    _, evidence, mock, _, _ = run_workflow(monkeypatch, tmp_path, decision="stop")
    assert evidence["followup"]["status"] == "stopped"
    assert len(evidence["steps"]) == 3
    assert sum(c["schema_name"] == "enterprise_investigation_followup" for c in mock.requests) == 1


@pytest.mark.parametrize("opts", [{"fail": True}, {"unapproved": True}])
def test_followup_failure_does_not_break_workflow(monkeypatch, tmp_path, opts):
    run_result, evidence, mock, _, _ = run_workflow(monkeypatch, tmp_path, **opts)
    assert evidence["followup"]["status"] == "fallback"
    assert evidence["followup"]["warning"] in {"ValueError", "LLMError"}
    assert len(evidence["steps"]) == 3
    assert run_result["status"] == "completed"
    assert len(mock.requests) == 4


def test_default_has_no_extra_hf_request(monkeypatch, tmp_path):
    _, evidence, mock, _, _ = run_workflow(monkeypatch, tmp_path, enabled=False)
    assert evidence["followup"]["status"] == "disabled"
    assert [c["schema_name"] for c in mock.requests] == [
        "enterprise_analysis_recommendation",
        "enterprise_investigation_checks",
        "enterprise_ai_briefing",
    ]

"""Offline Upgrade 7 tests: no Hugging Face inference requests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.investigation import (
    CHECKS,
    available_checks,
    execute_check,
    render_investigation_html,
    validate_check_selection,
    validate_review,
)
from aeai_os.agents.planner import PlannerAgent
from aeai_os.api.app import create_app
from aeai_os.data.profiling import profile_csv_dataset
from aeai_os.llm.gateway import LLMError
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import get_settings


class FakeQwen:
    model = "Qwen/Qwen3-32B"

    def __init__(self, fail_investigation=False, fail_review=False):
        self.requests = []
        self.fail_investigation = fail_investigation
        self.fail_review = fail_review

    def generate(self, **request):
        self.requests.append(request)
        name = request["schema_name"]
        if name == "enterprise_analysis_recommendation":
            return {
                "recipe": "procurement",
                "goals": ["summary", "summary", "outliers", "outliers"],
                "rationale": "Check procurement anomalies.",
            }
        if name == "enterprise_investigation_checks":
            if self.fail_investigation:
                raise LLMError("Simulated no-provider response")
            return {
                "checks": [
                    "anomaly_triage",
                    "supplier_concentration",
                    "anomaly_triage",
                    "data_quality",
                ],
                "focus": "Identify patterns that need review",
                "rationale": "Triangulate anomaly counts with supplier concentration and quality.",
            }
        if name == "enterprise_evidence_review":
            if self.fail_review:
                raise LLMError("Simulated reviewer outage")
            return {
                "evidence_ids": ["check_1", "check_2"],
                "summary": "Investigate the flagged patterns and confirm with source records.",
                "limitations": ["Statistical indicators alone are not proof of misconduct."],
            }
        if name == "enterprise_ai_briefing":
            return {
                "headline": "Evidence-led procurement review",
                "executive_summary": "Some purchasing patterns require verification.",
                "observations": ["Supplier concentration merits consideration."],
                "limitations": ["Verify original transaction evidence."],
            }
        raise AssertionError(f"Unexpected request: {name}")


def test_not_enabled_by_default(monkeypatch):
    monkeypatch.delenv("AEAI_DYNAMIC_REASONING_ENABLED", raising=False)
    assert get_settings().dynamic_reasoning_enabled is False
    profile = profile_csv_dataset("examples/procurement_demo.csv")
    plan, _ = PlannerAgent(llm_gateway=FakeQwen()).create_dynamic_plan(
        "run_123", "Analyze procurement spend and risks", profile
    )
    assert [node.agent for node in plan.nodes] == [
        "data_retrieval",
        "analytics_code",
        "visualization",
        "report",
        "evaluation",
    ]


def test_opt_in_governed_graph(monkeypatch):
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "true")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "true")
    profile = profile_csv_dataset("examples/procurement_demo.csv")
    plan, _ = PlannerAgent(llm_gateway=FakeQwen()).create_dynamic_plan(
        "run_123", "Analyze procurement spend and risks", profile
    )
    assert [node.agent for node in plan.nodes] == [
        "data_retrieval",
        "analytics_code",
        "visualization",
        "investigation",
        "report",
        "evaluation",
    ]
    investigator = next(node for node in plan.nodes if node.agent == "investigation")
    assert investigator.required_tools == ["artifact_reader"]
    assert investigator.depends_on == ["analytics"]
    assert "investigation" in next(node for node in plan.nodes if node.agent == "report").depends_on
    # Even an authorized LLM cannot request arbitrary tool permissions.
    assert "shell_exec" not in str(plan.model_dump())


def test_validation_deduplicates_but_never_exposes_unapproved_tools():
    proposed = {
        "checks": ["data_quality"] * 8 + ["dataset_overview"],
        "focus": "Check quality",
        "rationale": "Read evidence only",
    }
    assert validate_check_selection(proposed, ["data_quality", "dataset_overview"]) == [
        "data_quality",
        "dataset_overview",
    ]
    for tool in ["shell_exec", "snowflake_query", "__import__('os').system('date')"]:
        bad = {**proposed, "checks": [tool]}
        with pytest.raises(ValueError, match="unapproved"):
            validate_check_selection(bad, list(CHECKS))
    with pytest.raises(ValueError):
        validate_check_selection({**proposed, "unexpected": "ignore"}, list(CHECKS))


def test_evidence_review_rejects_unknown_ids_and_unsupported_numbers():
    valid = {
        "evidence_ids": ["check_1"],
        "summary": "Review supplier patterns.",
        "limitations": ["Confirm against source records."],
    }
    assert validate_review(valid, {"check_1"})["summary"] == valid["summary"]
    with pytest.raises(ValueError):
        validate_review({**valid, "evidence_ids": ["check_999"]}, {"check_1"})
    with pytest.raises(ValueError):
        validate_review({**valid, "summary": "Savings are 500%."}, {"check_1"})


def test_html_escapes_model_prose_and_aggregate_supplier_names():
    artifact = {
        "focus": '<script>alert("model")</script>',
        "selection_source": "llm",
        "model": "Qwen/Qwen3-32B",
        "steps": [
            {
                "evidence_id": "check_1",
                "check": "supplier_concentration",
                "source_paths": ["spend_by_supplier"],
                "facts": {"top_supplier": '<img src=x onerror="alert(1)">'},
            },
        ],
        "review": None,
    }
    html = render_investigation_html(artifact)
    assert "<script>" not in html
    assert "<img src=" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img src=" in html
    assert "<iframe" not in html


def _run(monkeypatch, tmp_path, *, fail_investigation=False, review=False, fail_review=False):
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "true")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "true")
    monkeypatch.setenv("AEAI_REASONING_REVIEW_ENABLED", str(review).lower())
    monkeypatch.setenv("AEAI_LLM_USAGE_LEDGER_PATH", str(tmp_path / "usage.jsonl"))
    mock = FakeQwen(fail_investigation=fail_investigation, fail_review=fail_review)
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **kwargs: mock)
    monkeypatch.setattr("aeai_os.agents.investigation.build_llm_gateway", lambda **kwargs: mock)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **kwargs: mock)
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze supplier spending, invoice anomalies and risks",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "completed"
    return repo, run, result, mock, client


def test_full_workflow_adds_evidence_without_changing_verified_analytics(monkeypatch, tmp_path):
    repo, run, result, mock, client = _run(monkeypatch, tmp_path)
    artifacts = result["artifacts"]
    kpis = next(a for a in artifacts if a["type"] == "kpi_table")
    assert kpis["metadata"]["total_spend"] == 165962.5
    assert result["evaluations"][0]["passed"] is True
    evidence = next(
        a for a in artifacts if a["metadata"].get("edition") == "investigation_evidence"
    )
    report = next(a for a in artifacts if a["metadata"].get("edition") == "investigation_report")
    assert report["metadata"]["verified_numerically"] is True
    assert evidence["id"] in report["source_artifact_ids"]
    payload = client.get(f"/runs/{run['id']}/artifacts/{evidence['id']}/content").json()
    assert payload["selection_source"] == "llm"
    assert [s["check"] for s in payload["steps"]] == [
        "anomaly_triage",
        "supplier_concentration",
        "data_quality",
    ]
    assert all(s["status"] == "verified_from_computed_artifacts" for s in payload["steps"])
    assert [call["schema_name"] for call in mock.requests] == [
        "enterprise_analysis_recommendation",
        "enterprise_investigation_checks",
        "enterprise_ai_briefing",
    ]
    assert any(
        e.node_id == "investigation" and e.payload.get("investigation_source") == "llm"
        for e in repo.list_events(run["id"])
    )
    event = next(e for e in repo.list_events(run["id"]) if e.node_id == "llm_budget")
    assert event.payload["llm_usage_summary"]["run_id"] == run["id"]


def test_provider_outage_falls_back_to_read_only_checks(monkeypatch, tmp_path):
    repo, run, result, mock, client = _run(monkeypatch, tmp_path, fail_investigation=True)
    evidence = next(
        a for a in result["artifacts"] if a["metadata"].get("edition") == "investigation_evidence"
    )
    payload = client.get(f"/runs/{run['id']}/artifacts/{evidence['id']}/content").json()
    assert payload["selection_source"] == "deterministic"
    assert payload["warning"] == "LLMError"
    assert payload["steps"]
    assert result["evaluations"][0]["passed"] is True


def test_optional_review_cites_only_verified_evidence(monkeypatch, tmp_path):
    _, run, result, mock, client = _run(monkeypatch, tmp_path, review=True)
    evidence = next(
        a for a in result["artifacts"] if a["metadata"].get("edition") == "investigation_evidence"
    )
    payload = client.get(f"/runs/{run['id']}/artifacts/{evidence['id']}/content").json()
    assert payload["review"]["evidence_ids"] == ["check_1", "check_2"]
    assert [c["schema_name"] for c in mock.requests] == [
        "enterprise_analysis_recommendation",
        "enterprise_investigation_checks",
        "enterprise_evidence_review",
        "enterprise_ai_briefing",
    ]


def test_generic_check_allowlist_and_deterministic_metrics():
    analysis = {
        "analysis_type": "generic",
        "dataset": {"row_count": 12, "column_count": 3},
        "kpis": {"row_count": 12, "completeness": 0.91, "duplicate_row_count": 1},
        "dimension_summaries": [
            {
                "column": "department",
                "unique_count": 2,
                "top_values": [{"value": "Sales", "count": 8, "share": 0.6667}],
            }
        ],
        "outliers": [{"column": "amount", "outlier_count": 2}],
    }
    assert "supplier_concentration" not in available_checks(analysis)
    assert execute_check("generic_segments", analysis)["facts"]["top_category_share"] == 0.6667
    with pytest.raises(ValueError):
        execute_check("supplier_concentration", analysis)

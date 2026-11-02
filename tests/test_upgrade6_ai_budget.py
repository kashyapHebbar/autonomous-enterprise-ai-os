"""Upgrade 6 regression tests: no Hugging Face network calls."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.llm.budget import (
    BudgetPolicy,
    LLMBudgetExceeded,
    llm_usage_scope,
)
from aeai_os.llm.gateway import HuggingFaceChatGateway, LLMError
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import AppSettings

SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "string"}},
    "required": ["x"],
    "additionalProperties": False,
}


def fake_response(usage=None, content='{"x":"ok"}'):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps(
                {
                    "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": usage,
                }
            ).encode()

    return Response()


def gateway_with_requests(requests, usage=None):
    def opener(request, *, timeout):
        requests.append(json.loads(request.data))
        return fake_response(usage)

    return HuggingFaceChatGateway(api_key="hf_test_secret_should_not_be_saved", opener=opener)


def policy(tmp_path, **kwargs):
    return BudgetPolicy(ledger_path=str(tmp_path / "usage.jsonl"), **kwargs)


def generate(gateway):
    return gateway.generate(
        instructions="Only return JSON",
        input_text="synthetic demo only",
        schema=SCHEMA,
        schema_name="test_schema",
        max_output_tokens=500,
    )


def test_budget_tracks_actual_provider_tokens_and_redacts_secrets(tmp_path):
    requests = []
    gateway = gateway_with_requests(requests, {"prompt_tokens": 150, "completion_tokens": 80})
    with llm_usage_scope("run_a", policy(tmp_path)) as tracker:
        assert generate(gateway) == {"x": "ok"}
        snapshot = tracker.snapshot()
    assert len(requests) == 1
    assert snapshot["model_calls"] == snapshot["model_calls_completed"] == 1
    assert snapshot["estimated_input_units"] == 150
    assert snapshot["estimated_output_units"] == 80
    assert snapshot["calls"][0]["usage_source"] == "provider"
    expected = (150 * 0.08 + 80 * 0.25) / 1_000_000
    assert snapshot["estimated_cost_usd"] == pytest.approx(expected)
    ledger = (tmp_path / "usage.jsonl").read_text()
    assert "hf_test_secret" not in ledger
    assert "synthetic demo" not in ledger
    assert '"action":"settle"' in ledger


def test_max_calls_blocked_before_http_and_recorded(tmp_path):
    requests = []
    gateway = gateway_with_requests(requests)
    with llm_usage_scope("run_a", policy(tmp_path, max_calls=1)) as tracker:
        generate(gateway)
        with pytest.raises(LLMBudgetExceeded, match="Maximum model calls"):
            generate(gateway)
        summary = tracker.snapshot()
    assert len(requests) == 1
    assert summary["model_calls_blocked"] == 1
    assert summary["calls"][-1]["reason"] == "max_calls"


def test_per_workflow_budget_blocks_before_http(tmp_path):
    requests = []
    gateway = gateway_with_requests(requests)
    with llm_usage_scope("run_a", policy(tmp_path, workflow_usd=0.000001)) as tracker:
        with pytest.raises(LLMBudgetExceeded, match="workflow AI cost budget"):
            generate(gateway)
        assert tracker.snapshot()["model_calls_blocked"] == 1
    assert requests == []


def test_monthly_limit_shared_between_scopes(tmp_path):
    requests = []
    gateway = gateway_with_requests(requests)
    # Each 500-token response reserves roughly $0.0002, and without provider
    # usage information remains conservatively booked at the reserved maximum.
    cfg = policy(tmp_path, monthly_usd=0.00023)
    with llm_usage_scope("run_a", cfg):
        generate(gateway)
    with llm_usage_scope("run_b", cfg) as tracker:
        with pytest.raises(LLMBudgetExceeded, match="monthly AI cost budget"):
            generate(gateway)
        assert tracker.snapshot()["model_calls_blocked"] == 1
    assert len(requests) == 1


def test_provider_failure_preserves_reservation_and_never_exposes_token(tmp_path):
    requests = []

    def opener(request, *, timeout):
        requests.append(request)
        raise HTTPError(request.full_url, 500, "sensitive information", None, None)

    gateway = HuggingFaceChatGateway(api_key="hf_top_secret", opener=opener)
    with llm_usage_scope("run_a", policy(tmp_path)) as tracker:
        with pytest.raises(LLMError, match="HTTP 500"):
            generate(gateway)
        summary = tracker.snapshot()
    assert summary["model_calls_failed"] == 1
    assert summary["estimated_cost_usd"] > 0
    assert "hf_top_secret" not in (tmp_path / "usage.jsonl").read_text()


def test_explicit_rate_configuration_changes_budget_estimates(tmp_path):
    assert policy(tmp_path, input_usd_per_million=2.0).price(1000, 1000) > policy(tmp_path).price(
        1000, 1000
    )
    for invalid in (
        {"max_calls": 0},
        {"workflow_usd": -1},
        {"max_output_tokens": 100},
        {"monthly_usd": 0},
    ):
        with pytest.raises(ValueError):
            policy(tmp_path, **invalid)


def test_end_to_end_hf_mock_calls_emit_usage_event_without_changing_kpis(monkeypatch, tmp_path):
    requests = []

    class Response:
        def __init__(self, result):
            self.result = result

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _max):
            return json.dumps(self.result).encode()

    def opener(request, *, timeout):
        body = json.loads(request.data)
        requests.append(body)
        if body["response_format"]["json_schema"]["name"] == "enterprise_analysis_recommendation":
            result = {
                "recipe": "procurement",
                "goals": ["summary", "trend", "summary"],
                "rationale": "Supplier and amount fields support analysis.",
            }
        else:
            result = {
                "headline": "Supplier spending review",
                "executive_summary": "Supplier spending and anomalous activity merit further checks.",  # noqa: E501
                "observations": ["Supplier concentration warrants review."],
                "limitations": ["Manual validation remains necessary."],
            }
        return Response(
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": {"prompt_tokens": 950, "completion_tokens": 130},
            }
        )

    gateway = HuggingFaceChatGateway(api_key="hf_mock_only", opener=opener)
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **kwargs: gateway)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **kwargs: gateway)
    cfg = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock_only",
        llm_usage_ledger_path=str(tmp_path / "usage.jsonl"),
    )
    monkeypatch.setattr("aeai_os.workflows.dynamic.get_settings", lambda: cfg)
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend and generate a dashboard",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert len(requests) == 2
    assert (
        next(a for a in body["artifacts"] if a["type"] == "kpi_table")["metadata"]["total_spend"]
        == 165962.5
    )
    events = repository.list_events(run["id"])
    planner = next(e for e in events if e.node_id == "planner")
    assert planner.payload["planner_source"] == "llm"
    usage = next(e.payload["llm_usage_summary"] for e in events if "llm_usage_summary" in e.payload)
    assert usage["model_calls"] == 2
    assert usage["model_calls_completed"] == 2
    assert usage["estimated_input_units"] == 1900
    assert usage["estimated_output_units"] == 260
    assert usage["estimated_cost_usd"] > 0
    assert any(a["metadata"].get("edition") == "ai_briefing" for a in body["artifacts"])


def test_workflow_fallback_when_budget_zero_network_requests(monkeypatch, tmp_path):
    requests = []
    gateway = gateway_with_requests(requests)
    monkeypatch.setattr("aeai_os.agents.planner.build_llm_gateway", lambda **kwargs: gateway)
    monkeypatch.setattr("aeai_os.agents.report.build_llm_gateway", lambda **kwargs: gateway)
    cfg = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock_only",
        llm_workflow_budget_usd=0.000001,
        llm_usage_ledger_path=str(tmp_path / "usage.jsonl"),
    )
    monkeypatch.setattr("aeai_os.workflows.dynamic.get_settings", lambda: cfg)
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement supplier spend",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert requests == []
    events = repository.list_events(run["id"])
    usage = next(e.payload["llm_usage_summary"] for e in events if "llm_usage_summary" in e.payload)
    assert usage["model_calls_blocked"] >= 1
    assert usage["model_calls"] == 0
    planner = next(e for e in events if e.node_id == "planner")
    assert planner.payload["planner_source"] == "deterministic"

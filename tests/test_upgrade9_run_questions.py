"""Upgrade 9 tests: all inference mocked, zero hosted Hugging Face calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.run_questions import (
    gather_verified_evidence,
    model_question_context,
    validate_grounded_answer,
)
from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import AppSettings


class FakeQwen:
    model = "Qwen/Qwen3-32B"

    def __init__(self, response=None):
        self.requests = []
        self.response = response

    def generate(self, **kwargs):
        self.requests.append(kwargs)
        evidence = json.loads(kwargs["input_text"])["approved_verified_evidence"]
        return self.response or {
            "answer": "Supplier concentration and anomaly signals deserve a careful review before any action.",  # noqa: E501
            "evidence_ids": [evidence[0]["id"], evidence[1]["id"]],
            "limitations": [
                "These findings are screening signals rather than proof of misconduct."
            ],
        }


@pytest.fixture
def ready_run(monkeypatch, tmp_path):
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "store"))
    run = client.post(
        "/runs",
        json={
            "task": "Review procurement risks",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    finished = client.post(f"/runs/{run['id']}/execute")
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    return client, repo, run["id"], tmp_path


def configure_qa(monkeypatch, tmp_path, gateway=None, *, enabled=True, limit=20, monthly=4.50):
    model = gateway or FakeQwen()
    cfg = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock_only",
        run_questions_enabled=enabled,
        run_questions_max_per_run=limit,
        llm_usage_ledger_path=str(tmp_path / "usage.jsonl"),
        llm_monthly_budget_usd=monthly,
    )
    monkeypatch.setattr("aeai_os.api.runs.get_settings", lambda: cfg)
    monkeypatch.setattr("aeai_os.api.runs.build_llm_gateway", lambda **kwargs: model)
    return model


def test_no_paid_requests_without_click(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = configure_qa(monkeypatch, tmp_path)
    response = client.get(f"/runs/{run_id}/questions")
    assert response.status_code == 200
    assert response.json() == []
    assert model.requests == []


def test_questions_are_opt_in(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = configure_qa(monkeypatch, tmp_path, enabled=False)
    response = client.post(
        f"/runs/{run_id}/questions", json={"question": "What deserves investigation?"}
    )
    assert response.status_code == 409
    assert model.requests == []


def test_question_generates_evidence_with_history_and_one_model_call(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = configure_qa(monkeypatch, tmp_path)
    response = client.post(
        f"/runs/{run_id}/questions", json={"question": "Which supplier risks matter most?"}
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["question"] == "Which supplier risks matter most?"
    assert answer["model"] == "Qwen/Qwen3-32B"
    assert answer["evidence"]
    assert all(e["source_artifact_id"] for e in answer["evidence"])
    assert len(model.requests) == 1
    assert model.requests[0]["schema_name"] == "enterprise_run_question_answer"
    assert "dataset_uri" not in model.requests[0]["input_text"]
    assert "examples/procurement_demo.csv" not in model.requests[0]["input_text"]
    assert client.get(f"/runs/{run_id}/questions").json()[0]["id"] == answer["id"]
    assert any("question_usage_summary" in event.payload for event in repo.list_events(run_id))
    assert client.get(f"/runs/{run_id}").json()["status"] == "completed"


def test_question_rejects_unverified_numbers_and_does_not_persist(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = FakeQwen(
        {
            "answer": "The supplier stole $999999 and should be prosecuted.",
            "evidence_ids": ["evidence_data_quality"],
            "limitations": [],
        }
    )
    configure_qa(monkeypatch, tmp_path, gateway=model)
    result = client.post(
        f"/runs/{run_id}/questions", json={"question": "What happened to supplier spending?"}
    )
    assert result.status_code == 502
    assert client.get(f"/runs/{run_id}/questions").json() == []


def test_bad_evidence_refs_are_not_accepted(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = FakeQwen(
        {
            "answer": "There may be a supplier risk based on the provided metrics.",
            "evidence_ids": ["evidence_nonexistent"],
            "limitations": [],
        }
    )
    configure_qa(monkeypatch, tmp_path, gateway=model)
    assert (
        client.post(
            f"/runs/{run_id}/questions", json={"question": "Which suppliers are risky?"}
        ).status_code
        == 502
    )


def test_per_run_question_limit_avoids_additional_paid_calls(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = configure_qa(monkeypatch, tmp_path, limit=1)
    assert (
        client.post(
            f"/runs/{run_id}/questions", json={"question": "What are the supplier risks?"}
        ).status_code
        == 200
    )
    response = client.post(
        f"/runs/{run_id}/questions", json={"question": "What are the savings risks?"}
    )
    assert response.status_code == 429
    assert len(model.requests) == 1


def test_invalid_question_rejected_before_model_call(ready_run, monkeypatch):
    client, repo, run_id, tmp_path = ready_run
    model = configure_qa(monkeypatch, tmp_path)
    assert client.post(f"/runs/{run_id}/questions", json={"question": "short"}).status_code == 422
    assert client.post(f"/runs/{run_id}/questions", json={"question": "x" * 601}).status_code == 422
    assert not model.requests


def test_only_verified_aggregates_reach_model():
    analysis = {
        "analysis_type": "procurement",
        "dataset": {
            "row_count": 44,
            "invalid_amount_rows": 0,
            "raw_rows": [{"secret": "DONOTLEAK"}],
        },
        "kpis": {"supplier_count": 1, "total_spend": 100.0},
        "spend_by_supplier": [{"supplier": "Vendor X", "share": 1.0, "spend": 100.0}],
        "missing_data_risks": [],
    }
    entries = gather_verified_evidence(analysis, "kpi_abc")
    compact = model_question_context("Where is spend concentrated?", entries)
    assert "DONOTLEAK" not in compact
    assert "raw_rows" not in compact
    assert "kpi_abc" not in compact
    assert "Vendor X" in compact
    assert "evidence_key_figures" in compact


@pytest.mark.parametrize(
    "wrong",
    [
        {"answer": "Spend rose 12% last month."},
        {"evidence_ids": ["not_a_real_id"]},
        {"evidence_ids": []},
        {"limitations": ["Costs increased by $30"]},
        {"answer": "ok"},
        {"extra": "don't accept this"},
    ],
)
def test_strict_validation(wrong):
    evidence = [
        {
            "id": "evidence_data_quality",
            "label": "Data quality",
            "facts": {},
            "source_paths": [],
            "source_artifact_id": "abc",
        }
    ]
    valid = {
        "answer": "The quality check suggests manual follow-up is appropriate.",
        "evidence_ids": ["evidence_data_quality"],
        "limitations": [],
    }
    with pytest.raises(ValueError):
        validate_grounded_answer({**valid, **wrong}, evidence)

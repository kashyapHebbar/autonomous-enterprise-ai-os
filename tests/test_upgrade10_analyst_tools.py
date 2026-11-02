"""Upgrade 10 regression and access tests — all provider responses are mocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.analyst_tools import (
    _eligible_plan,
    load_run_aggregates,
    run_approved_tool,
)
from aeai_os.api.app import create_app
from aeai_os.llm.budget import current_usage_tracker
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import AppSettings


class FakeQwen:
    model = "Qwen/Qwen3-32B"

    def __init__(self, plan=None, fail_explanation=False):
        self.calls = []
        self.plan = plan or {
            "tool": "supplier_totals",
            "supplier": None,
            "first_month": None,
            "last_month": None,
            "rationale": "Supplier spending warrants a comparison.",
        }
        self.fail_explanation = fail_explanation

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        tracker = current_usage_tracker()
        reservation = (
            tracker.begin(
                purpose="analyst_test",
                model=self.model,
                body=json.dumps(kwargs),
                max_output_tokens=kwargs["max_output_tokens"],
            )
            if tracker
            else None
        )
        if kwargs["schema_name"] == "enterprise_analyst_tool_plan":
            result = self.plan
        elif self.fail_explanation:
            if tracker and reservation:
                tracker.finish(
                    reservation, {"prompt_tokens": 100, "completion_tokens": 100}, succeeded=False
                )
            raise ValueError("Model response was unusable")
        else:
            result = {
                "answer": "Supplier totals indicate differences in the concentration of spending. Examine the individual source records before attributing causes.",  # noqa: E501
                "evidence_ids": ["verified_calculation"],
                "limitations": ["Aggregate spending does not establish misconduct."],
            }
        if tracker and reservation:
            tracker.finish(
                reservation, {"prompt_tokens": 120, "completion_tokens": 90}, succeeded=True
            )
        return result


@pytest.fixture
def ready_run(monkeypatch, tmp_path):
    for name in (
        "AEAI_DYNAMIC_REASONING_ENABLED",
        "AEAI_REASONING_FOLLOWUPS_ENABLED",
        "AEAI_LLM_ENABLED",
    ):
        monkeypatch.setenv(name, "false")
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze supplier spending",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    result = client.post(f"/runs/{run['id']}/execute")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    return client, repo, run["id"], tmp_path


def mock_config(monkeypatch, tmp_path, model=None, enabled=True, commentary=True, max_items=15):
    gateway = model or FakeQwen()
    settings = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock_only",
        analyst_tools_enabled=enabled,
        analyst_commentary_enabled=commentary,
        analyst_tools_max_per_run=max_items,
        llm_usage_ledger_path=str(tmp_path / "usage.jsonl"),
    )
    monkeypatch.setattr("aeai_os.api.runs.get_settings", lambda: settings)
    monkeypatch.setattr("aeai_os.api.runs.build_llm_gateway", lambda **_kwargs: gateway)
    return gateway


def test_no_calls_for_opening_page(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp)
    assert client.get(f"/runs/{id}/analyst-tools").json() == []
    assert model.calls == []


def test_disabled_prevents_provider_calls(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp, enabled=False)
    res = client.post(
        f"/runs/{id}/analyst-tools", json={"question": "Compare spending by supplier"}
    )
    assert res.status_code == 409
    assert len(model.calls) == 0


def test_verified_chart_is_saved_no_workflow_rerun(ready_run, monkeypatch):
    client, repo, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp)
    res = client.post(
        f"/runs/{id}/analyst-tools", json={"question": "Compare spending by supplier"}
    )
    assert res.status_code == 200, res.text
    record = res.json()
    assert record["tool"] == "supplier_totals"
    assert record["chart_kind"] == "bar"
    assert len(record["points"]) >= 1
    assert all(row["transactions"] >= 2 for row in record["points"])
    assert abs(record["verified_total"] - sum(p["value"] for p in record["points"])) < 0.0001
    assert record["model_calls"] == 2
    assert len(model.calls) == 2
    assert "invoice_id" not in model.calls[0]["input_text"]
    assert "examples/procurement_demo.csv" not in model.calls[0]["input_text"]
    assert "row_number" not in model.calls[1]["input_text"]
    saved = client.get(f"/runs/{id}/analyst-tools").json()
    assert saved[0]["id"] == record["id"]
    assert client.get(f"/runs/{id}").json()["status"] == "completed"
    assert any("analyst_usage_summary" in e.payload for e in repo.list_events(id))


def test_one_call_when_commentary_disabled(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp, commentary=False)
    res = client.post(
        f"/runs/{id}/analyst-tools", json={"question": "Compare spending by supplier"}
    )
    assert res.status_code == 200, res.text
    assert len(model.calls) == 1
    assert res.json()["model_calls"] == 1


def test_bad_second_answer_keeps_calculation(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp, model=FakeQwen(fail_explanation=True))
    res = client.post(f"/runs/{id}/analyst-tools", json={"question": "Compare supplier spending"})
    assert res.status_code == 200, res.text
    assert "AI explanation unavailable" in " ".join(res.json()["limitations"])
    assert res.json()["points"]
    assert len(model.calls) == 2


@pytest.mark.parametrize(
    "tool", ["arbitrary_python", "execute_sql", "read_file", "write_record", "request_url"]
)
def test_unapproved_tools_are_rejected_before_execution(tool):
    dataset = {"departments": [], "categories": ["X"], "suppliers": ["V"], "months": ["2026-01"]}
    with pytest.raises(ValueError):
        _eligible_plan(
            {
                "tool": tool,
                "supplier": None,
                "first_month": None,
                "last_month": None,
                "rationale": "x",
            },
            dataset,
        )


def test_unapproved_supplier_rejected():
    data = {"departments": [], "categories": ["X"], "suppliers": ["Known"], "months": ["2026-01"]}
    with pytest.raises(ValueError):
        _eligible_plan(
            {
                "tool": "supplier_monthly_trend",
                "supplier": "NotPresent",
                "first_month": None,
                "last_month": None,
                "rationale": "x",
            },
            data,
        )


def test_suppresses_single_transaction_groups():
    dataset = {
        "rows": [
            ("A", "X", "D", "2026-01", 100.0),
            ("A", "X", "D", "2026-01", 200.0),
            ("B", "Y", "D", "2026-02", 99.0),
        ],
        "months": ["2026-01", "2026-02"],
    }
    plan = {"tool": "supplier_totals", "supplier": None, "first_month": None, "last_month": None}
    result = run_approved_tool(plan, dataset, "USD")
    assert result["points"] == [{"label": "A", "value": 300.0, "transactions": 2}]
    assert any("suppressed" in note for note in result["limitations"])


def test_csv_scope_rejects_unmanaged_file(tmp_path):
    file = tmp_path / "secrets.csv"
    file.write_text("supplier,amount\nAlpha,500\n")
    with pytest.raises(ValueError, match="outside"):
        load_run_aggregates(
            str(file),
            {"dataset": {"resolved_columns": {"supplier": "supplier", "amount": "amount"}}},
            tmp_path / "managed",
        )


def test_no_tool_result_if_invalid_plan(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(
        monkeypatch,
        tmp,
        model=FakeQwen(
            {
                "tool": "delete_database",
                "supplier": None,
                "first_month": None,
                "last_month": None,
                "rationale": "bad",
            }
        ),
    )
    res = client.post(f"/runs/{id}/analyst-tools", json={"question": "Run the supplier analysis"})
    assert res.status_code == 422
    assert client.get(f"/runs/{id}/analyst-tools").json() == []
    assert len(model.calls) == 1


def test_question_limit_prevents_paid_call(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(monkeypatch, tmp, max_items=1)
    assert (
        client.post(
            f"/runs/{id}/analyst-tools", json={"question": "Compare supplier spending"}
        ).status_code
        == 200
    )
    res = client.post(
        f"/runs/{id}/analyst-tools", json={"question": "Compare supplier spending again"}
    )
    assert res.status_code == 429
    assert len(model.calls) == 2


def test_model_plan_is_rejected_when_fields_not_known(ready_run, monkeypatch):
    client, _, id, tmp = ready_run
    model = mock_config(
        monkeypatch,
        tmp,
        model=FakeQwen(
            {
                "tool": "period_comparison",
                "supplier": None,
                "first_month": "2999-01",
                "last_month": "2026-06",
                "rationale": "X",
            }
        ),
    )
    res = client.post(
        f"/runs/{id}/analyst-tools", json={"question": "Compare March and June spending"}
    )
    assert res.status_code == 422
    assert len(model.calls) == 1


def test_changed_csv_is_rejected_as_stale_evidence(tmp_path):
    folder = tmp_path / "managed"
    folder.mkdir()
    csv_path = folder / "dataset.csv"
    csv_path.write_text("supplier,spend_amount\nAlpha,100\nAlpha,200\n", encoding="utf-8")
    analysis = {
        "dataset": {
            "row_count": 2,
            "resolved_columns": {"supplier": "supplier", "amount": "spend_amount"},
        },
        "kpis": {"total_spend": 300},
    }
    valid = load_run_aggregates(str(csv_path), analysis, folder)
    assert len(valid["rows"]) == 2
    csv_path.write_text("supplier,spend_amount\nAlpha,400\nAlpha,200\n", encoding="utf-8")
    with pytest.raises(ValueError, match="totals changed"):
        load_run_aggregates(str(csv_path), analysis, folder)


def test_frontend_api_contract_and_router_basename_preserved():
    # Prevent accidental replacement of the custom FastAPI /app integration.
    source = Path("frontend/src")
    assert 'basename="/app"' in (source / "main.tsx").read_text()
    assert "Original UI" in (source / "components/Layout.tsx").read_text()
    api_code = (source / "api.ts").read_text()
    assert "/analyst-tools" in api_code
    page = (source / "pages/AIAnalyst.tsx").read_text()
    assert "AnalystCalculationsPanel" in page
    assert "AskRunPanel" in page

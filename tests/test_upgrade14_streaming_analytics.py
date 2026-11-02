"""Upgrade 14: bounded streaming financial overview, access and safety. No LLM calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.scaling.summary import ScalingError, stream_financial_summary


def test_existing_example_matches_financial_engine_and_does_not_claim_risk():
    from aeai_os.analytics.kpis import analyze_procurement_dataset
    from aeai_os.data.adapters import CsvDatasetAdapter

    path = Path("examples/procurement_demo.csv")
    expected = analyze_procurement_dataset(CsvDatasetAdapter.from_path(path)).to_dict()
    result = stream_financial_summary(path)
    assert result["metrics"]["total_spend"] == expected["kpis"]["total_spend"]
    assert result["metrics"]["rows_scanned"] == expected["dataset"]["row_count"]
    assert result["metrics"]["supplier_count"] == expected["kpis"]["supplier_count"]
    assert result["hugging_face_requests"] == 0
    assert result["coverage"] == "full_source_financial_aggregates_only"
    assert "anomaly_count" not in result["metrics"]


def test_public_government_sample_has_exact_total():
    path = Path("/mnt/data/ai_os_procurement_test.csv")
    if path.exists():
        result = stream_financial_summary(path)
        assert result["metrics"]["total_spend"] == 289372
        assert result["metrics"]["rows_scanned"] == 44


def test_missing_and_invalid_amounts_and_small_group_suppression(tmp_path):
    p = tmp_path / "records.csv"
    p.write_text(
        'supplier,category,amount,date\nA,X,"$1,200.50",2026-01-01\nA,X,-20,2026-01-02\nB,Y,NA,2026-01-03\nC,Y,not-a-number,2026-01-04\nD,Y,5,2026-02-03\n',
        encoding="utf8",
    )
    result = stream_financial_summary(p)
    assert result["metrics"]["total_spend"] == 1185.5
    assert result["metrics"]["invalid_amount_rows"] == 2
    assert result["suppliers"]["groups_suppressed"] == 1
    assert len(result["suppliers"]["items"]) == 1
    assert result["suppliers"]["items"][0]["name"] == "A"
    assert len(result["monthly_spend"]) == 2


def test_no_partial_result_after_capacity_limits(tmp_path):
    p = tmp_path / "sample.csv"
    p.write_text("supplier,category,amount\nA,X,10\nB,X,20\nA,X,30\n")
    with pytest.raises(ScalingError, match="Row limit reached"):
        stream_financial_summary(p, row_limit=2)


def test_header_whitespace_handled_consistently(tmp_path):
    p = tmp_path / "headers.csv"
    p.write_text(" supplier , category , amount \nA,X,10\nA,X,20\n")
    result = stream_financial_summary(p)
    assert result["metrics"]["total_spend"] == 30
    assert result["column_roles"]["supplier"] == "supplier"


def test_tenant_access_and_saved_event_without_api_model_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    repo = InMemoryRunRepository()
    app = create_app(repository=repo, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = client.post(
        "/runs",
        json={
            "task": "Real procurement spending",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    assert (
        client.get(f"/scaling/runs/{run['id']}/financial-overview").json()["status"]
        == "not_scanned"
    )
    res = client.post(f"/scaling/runs/{run['id']}/financial-overview")
    assert res.status_code == 200, res.text
    assert res.json()["metrics"]["total_spend"] == 165962.5
    assert (
        client.get(f"/scaling/runs/{run['id']}/financial-overview").json()["status"] == "completed"
    )
    assert repo.get_run(run["id"]).status.value == "pending"
    assert any("scaling_financial_overview" in e.payload for e in repo.list_events(run["id"]))
    private = repo.create_run(
        "Other tenant", metadata={"organization_id": "different-org", "workspace_id": "default"}
    )
    assert client.get(f"/scaling/runs/{private.id}/financial-overview").status_code == 404
    assert client.post(f"/scaling/runs/{private.id}/financial-overview").status_code == 404


def test_source_changed_during_scan_is_rejected(monkeypatch, tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("supplier,category,amount\nA,X,10\nA,X,10\n")
    original = Path.stat
    calls = [0]

    def unstable(self, *a, **kw):
        value = original(self, *a, **kw)
        if self == p:
            calls[0] += 1
            if calls[0] == 3:
                p.write_text("supplier,category,amount\nA,X,99\nA,X,99\n")
                value = original(self)
        return value

    monkeypatch.setattr(Path, "stat", unstable)
    with pytest.raises(ScalingError, match="changed during"):
        stream_financial_summary(p)


def test_frontend_routes_and_legacy_app_remain_intact():
    root = Path(__file__).resolve().parents[1]
    assert (
        '<Route path="scale" element={<ScalableData/>}/>'
        in (root / "frontend/src/App.tsx").read_text()
    )
    assert 'href="/legacy-app"' in (root / "frontend/src/components/Layout.tsx").read_text()
    assert 'basename="/app"' in (root / "frontend/src/main.tsx").read_text()
    assert (
        "build_scaling_router(run_repository, artifact_store)"
        in (root / "src/aeai_os/api/app.py").read_text()
    )

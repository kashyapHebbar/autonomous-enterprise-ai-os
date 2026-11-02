"""Upgrade 11.5 safe visualizations. All tests are offline; no LLM calls."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.intelligence.visualizations import MAX_CELLS, build_visualization_cube
from aeai_os.runs.repository import InMemoryRunRepository


def _data(tmp_path):
    p = tmp_path / "demo.csv"
    p.write_text(
        "supplier,category,department,date,amount,invoice_id\n"
        "A,Hardware,IT,2026-01-03,100,INV-SECRET-1\n"
        "A,Hardware,IT,2026-01-04,150,INV-SECRET-2\n"
        "B,Travel,Sales,2026-02-04,50,INV-SECRET-3\n"
        "B,Travel,Sales,2026-02-05,55,INV-SECRET-4\n"
        "C,Travel,IT,2026-01-02,1000,INV-SECRET-PRIVATE\n",
        encoding="utf-8",
    )
    analysis = {
        "dataset": {
            "row_count": 5,
            "resolved_columns": {
                "supplier": "supplier",
                "category": "category",
                "department": "department",
                "date": "date",
                "amount": "amount",
            },
            "currency": "USD",
        },
        "kpis": {"total_spend": 1355.0},
    }
    return p, analysis


def test_eligible_cohorts_hide_singletons_and_row_level_details(tmp_path):
    p, a = _data(tmp_path)
    data = build_visualization_cube(str(p), a, tmp_path)
    assert data["covered_transactions"] == 4
    assert data["suppressed_cells"] == 1
    assert len(data["cells"]) == 2
    assert all(x["transactions"] >= 2 for x in data["cells"])
    assert data["cells"][0]["amount"] == 250.0
    assert data["cells"][1]["amount"] == 105.0
    assert "1355" not in str(data)
    assert "INV-SECRET" not in str(data)
    assert "1000" not in str(data)
    assert set(data["cells"][0]) == {
        "supplier",
        "category",
        "department",
        "month",
        "amount",
        "transactions",
    }


def test_stale_totals_block_cross_data(tmp_path):
    p, a = _data(tmp_path)
    a["kpis"]["total_spend"] = 50.0
    with pytest.raises(ValueError, match="changed"):
        build_visualization_cube(str(p), a, tmp_path)


def test_outside_allowlist_is_not_read(tmp_path):
    p, a = _data(tmp_path)
    with pytest.raises(ValueError, match="outside"):
        build_visualization_cube(str(p), a, tmp_path / "another-root")


def test_cube_limits_and_no_model_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    repo = InMemoryRunRepository()
    app = create_app(repository=repo, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    assert client.get("/runs/nonexistent/visualization-cube").status_code == 404
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spending for comparison",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    assert client.get(f"/runs/{run['id']}/visualization-cube").status_code == 409
    response = client.post(f"/runs/{run['id']}/execute")
    assert response.status_code == 200, response.text
    output = client.get(f"/runs/{run['id']}/visualization-cube")
    assert output.status_code == 200, output.text
    payload = output.json()
    assert set(payload) == {
        "cells",
        "dimensions",
        "covered_transactions",
        "suppressed_cells",
        "note",
    }
    assert len(payload["cells"]) <= MAX_CELLS
    assert "kpis" not in payload
    assert all(c["transactions"] >= 2 for c in payload["cells"])
    assert "invoice_id" not in str(payload)
    assert "Hugging Face" not in payload["note"]


def test_frontend_routing_keeps_custom_fastapi_basename():
    root = Path(__file__).resolve().parents[1] / "frontend/src"
    assert 'basename="/app"' in (root / "main.tsx").read_text()
    assert 'href="/legacy-app"' in (root / "components/Layout.tsx").read_text()
    assert "visualizations" in (root / "App.tsx").read_text()
    assert "Visualization Studio" in (root / "components/Layout.tsx").read_text()
    assert "localStorage" in (root / "pages/Visualizations.tsx").read_text()
    assert "downloadChartCSV" in (root / "components/VizCharts.tsx").read_text()
    assert "https://api.openai.com" not in (root / "pages/Visualizations.tsx").read_text()


def test_visualization_cube_is_access_controlled(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    repo = InMemoryRunRepository()
    private = repo.create_run(
        "Private organization dataset",
        metadata={"organization_id": "another-org", "workspace_id": "default"},
    )
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    assert client.get(f"/runs/{private.id}/visualization-cube").status_code in {403, 404}


def test_spending_without_eligible_groups_returns_empty(tmp_path):
    p, a = _data(tmp_path)
    p.write_text(
        "supplier,category,department,date,amount,invoice_id\n"
        "A,Hardware,IT,2026-01-01,10,S1\n"
        "B,Travel,Sales,2026-02-01,20,S2\n",
        encoding="utf8",
    )
    a["dataset"]["row_count"] = 2
    a["kpis"]["total_spend"] = 30.0
    data = build_visualization_cube(str(p), a, tmp_path)
    assert data["cells"] == []
    assert data["suppressed_cells"] == 2
    assert data["covered_transactions"] == 0

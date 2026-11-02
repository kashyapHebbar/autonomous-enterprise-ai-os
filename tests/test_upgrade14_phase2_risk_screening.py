"""Upgrade 14 Phase 2: no provider/network calls, persisted checkpoints and governed API."""

from __future__ import annotations

import csv
from pathlib import Path

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.scaling.risk import latest_scan, process_next, set_scan_action, start_scan


def sample(path: Path, size=1600):
    with path.open("w", newline="", encoding="utf8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [" supplier ", "category", "transaction_amount", "transaction_date", "invoice_id"]
        )
        for i in range(size):
            writer.writerow(
                [
                    "V" + str(i % 4),
                    "Office" if i % 2 else "Hardware",
                    "5000" if i == 2 else ("200" if i % 5 else "100"),
                    "2026-01-03" if i < 50 else "2026-01-04",
                    "INV-SAME" if i in (1, 2) else f"INV-{i}",
                ]
            )


def test_disk_screening_reconciles_and_counts_flags(tmp_path):
    file = tmp_path / "records.csv"
    db = tmp_path / "risk.db"
    sample(file, 1200)
    job = start_scan("run1", file, "org", "ws", db_path=db)
    assert job["status"] == "queued"
    assert process_next(db_path=db) == job["id"]
    status = latest_scan("run1", "org", "ws", db_path=db)
    assert status["status"] == "completed", status
    assert status["rows_scanned"] == 1200
    assert status["valid_amount_rows"] == 1200
    assert status["result"]["signals"]["unusually_high_amount_transactions"] >= 1
    assert status["result"]["signals"]["repeated_transaction_pattern_groups"] >= 1
    assert status["result"]["signals"]["repeated_invoice_identifier_groups"] == 1
    assert status["result"]["hugging_face_requests"] == 0
    assert "not_fraud" in status["result"]["coverage"]
    # Private scoped store: other workspace should never see this result.
    assert latest_scan("run1", "other", "ws", db_path=db) is None


def test_cancel_resume_and_source_change(tmp_path):
    file = tmp_path / "data.csv"
    db = tmp_path / "risk.db"
    sample(file, 1700)
    first = start_scan("r2", file, "o", "w", db_path=db)
    n = [0]

    def stop():
        n[0] += 1
        return n[0] > 650

    process_next(db_path=db, stop=stop)
    status = latest_scan("r2", "o", "w", db_path=db)
    assert status["status"] == "interrupted"
    assert 500 <= status["rows_scanned"] < 1700
    set_scan_action("r2", first["id"], "o", "w", "resume", db_path=db)
    process_next(db_path=db)
    status = latest_scan("r2", "o", "w", db_path=db)
    assert status["status"] == "completed"
    assert status["rows_scanned"] == 1700
    cancelled = start_scan("r3", file, "o", "w", db_path=db)
    set_scan_action("r3", cancelled["id"], "o", "w", "cancel", db_path=db)
    assert latest_scan("r3", "o", "w", db_path=db)["status"] == "cancelled"
    file.write_text(file.read_text() + "V,X,5,2026-01-01,INV-X\n")
    import pytest

    from aeai_os.scaling.summary import ScalingError

    with pytest.raises(ScalingError, match="changed"):
        set_scan_action("r3", cancelled["id"], "o", "w", "resume", db_path=db)


def test_api_gated_and_does_not_change_original_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    monkeypatch.setenv("AEAI_RISK_DB_PATH", str(tmp_path / "risk.db"))
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    file = tmp_path / "my.csv"
    sample(file, 30)
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post("/runs", json={"task": "test risk", "dataset_uri": str(file)}).json()
    run_id = run["id"]
    assert client.get(f"/scaling/runs/{run_id}/risk-scan").json()["status"] == "not_started"
    response = client.post(f"/scaling/runs/{run_id}/risk-scan")
    assert response.status_code == 202, response.text
    scan = response.json()
    assert "source_path" not in scan
    assert client.post(f"/scaling/runs/{run_id}/risk-scan/{scan['id']}/cancel").status_code == 200
    assert client.post(f"/scaling/runs/{run_id}/risk-scan/{scan['id']}/resume").status_code == 200
    process_next(db_path=tmp_path / "risk.db")
    assert client.get(f"/scaling/runs/{run_id}/risk-scan").json()["status"] == "completed"
    assert repo.get_run(run_id).status.value == "pending"
    other = repo.create_run(
        "private", metadata={"organization_id": "different-org", "workspace_id": "default"}
    )
    assert client.get(f"/scaling/runs/{other.id}/risk-scan").status_code == 404


def test_integrated_local_and_compose_worker_contract():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts/launch_ai_os.py").read_text()
    compose = (root / "docker-compose.yml").read_text()
    ui = (root / "frontend/src/pages/ScalableData.tsx").read_text()
    app = (root / "src/aeai_os/api/app.py").read_text()
    assert "scripts/run_risk_worker.py" in launcher
    assert "risk-worker:" in compose
    assert "<RiskScreeningPanel runId={selected}/>" in ui
    assert "build_scaling_router(run_repository, artifact_store)" in app
    assert 'basename="/app"' in (root / "frontend/src/main.tsx").read_text()
    assert 'href="/legacy-app"' in (root / "frontend/src/components/Layout.tsx").read_text()

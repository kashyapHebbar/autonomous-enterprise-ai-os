"""Upgrade 13: streaming reconciliation, access boundaries and worker integration.

All tests are deterministic, offline and do not use hosted LLM calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aeai_os.analytics.kpis import analyze_procurement_dataset
from aeai_os.api.app import create_app
from aeai_os.data.adapters import CsvDatasetAdapter
from aeai_os.quality.reconcile import stream_reconcile
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.storage import LocalArtifactStore
from aeai_os.workflows.worker import WorkflowWorker, enqueue_dynamic_workflow


def analysis(path):
    return analyze_procurement_dataset(CsvDatasetAdapter.from_path(path)).to_dict()


def test_offline_streaming_reconciliation_matches_real_engine_example():
    source = Path("examples/procurement_demo.csv").resolve()
    result = stream_reconcile(source, analysis(source))
    assert result["status"] == "verified"
    assert result["checks_passed"] == result["checks_total"] == 7
    assert result["rows_scanned"] > 0
    assert result["independently_calculated_total"] == 165962.5
    assert result["duration_seconds"] >= 0


def test_tampered_source_total_is_detected(tmp_path):
    source = tmp_path / "test.csv"
    source.write_text("supplier,category,amount\nA,Hardware,100\nA,Hardware,200\nB,Software,300\n")
    result = analysis(source)
    assert stream_reconcile(source, result)["status"] == "verified"
    source.write_text(source.read_text().replace("300", "999"))
    bad = stream_reconcile(source, result)
    assert bad["status"] == "mismatch"
    assert bad["checks"]["total_spending"] is False
    assert bad["checks"]["supplier_breakdown"] is False


def test_hard_row_limit_prevents_heavy_audit(tmp_path):
    source = tmp_path / "big.csv"
    source.write_text("supplier,category,amount\n" + "A,Hardware,3\n" * 12)
    outcome = stream_reconcile(
        source,
        {
            "dataset": {
                "resolved_columns": {
                    "supplier": "supplier",
                    "category": "category",
                    "amount": "amount",
                }
            }
        },
        max_rows=10,
    )
    assert outcome["status"] == "skipped"
    assert outcome["rows_scanned"] == 10


def test_invalid_numeric_and_missing_values_follow_engine_semantics(tmp_path):
    source = tmp_path / "values.csv"
    source.write_text(
        'supplier,category,amount\nA,X,"$1,200.50"\nA,X,NA\nB,Y,-5\nC,Z,not_a_number\n'
    )
    result = analysis(source)
    verification = stream_reconcile(source, result)
    assert verification["status"] == "verified"
    assert verification["valid_amount_rows"] == 2
    assert verification["independently_calculated_total"] == 1195.5


def test_worker_runs_audit_and_authenticated_dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitoring.db"))
    repo = InMemoryRunRepository()
    store = LocalArtifactStore(tmp_path / "artifacts")
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend in synthetic records",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    enqueue_dynamic_workflow(repo, run["id"])
    worker = WorkflowWorker(
        repository=repo, artifact_root=tmp_path / "artifacts", artifact_store=store
    )
    job = worker.process_next_job()
    assert job is not None and job.status.value == "completed"
    verify = client.get(f"/performance/runs/{run['id']}/verification")
    assert verify.status_code == 200, verify.text
    assert verify.json()["status"] == "verified", verify.json()
    status = client.get("/performance/summary").json()
    assert status["verification"]["verified"] == 1
    assert status["audited_rows"] > 0
    assert status["average_job_duration_seconds"] is not None
    assert "openai" not in verify.text.lower()


def test_other_workspace_cannot_see_verification(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitors.db"))
    repo = InMemoryRunRepository()
    private = repo.create_run(
        "Private spending", metadata={"organization_id": "not-your-org", "workspace_id": "default"}
    )
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    assert client.get(f"/performance/runs/{private.id}/verification").status_code == 404
    assert client.get("/performance/summary").json()["runs_sampled"] == 0


def test_frontend_exposes_only_read_only_approved_api_and_preserves_custom_routing():
    root = Path(__file__).resolve().parents[1]
    assert (
        "build_performance_router(run_repository)" in (root / "src/aeai_os/api/app.py").read_text()
    )
    assert 'basename="/app"' in (root / "frontend/src/main.tsx").read_text()
    assert 'href="/legacy-app"' in (root / "frontend/src/components/Layout.tsx").read_text()
    assert "IntelligencePerformance" in (root / "frontend/src/pages/Home.tsx").read_text()
    assert "VerificationPanel" in (root / "frontend/src/pages/WorkflowDetail.tsx").read_text()
    assert (
        "HF_TOKEN" not in (root / "frontend/src/components/IntelligencePerformance.tsx").read_text()
    )


def test_csv_capacity_guard_warns_before_memory_heavy_profile(tmp_path):
    from pytest import raises

    from aeai_os.quality.reconcile import check_local_csv_capacity

    path = tmp_path / "oversize.csv"
    with path.open("wb") as handle:
        handle.truncate(2 * 1024 * 1024)
    with raises(ValueError, match="representative sample"):
        check_local_csv_capacity(path, max_mib=1)
    check_local_csv_capacity(path, max_mib=3)


def test_csv_header_whitespace_is_normalized_like_main_adapter(tmp_path):
    source = tmp_path / "space.csv"
    source.write_text(" supplier , category , amount \nA,X,10\nA,Y,20\n")
    result = analysis(source)
    checked = stream_reconcile(source, result)
    assert checked["status"] == "verified"
    assert checked["independently_calculated_total"] == 30

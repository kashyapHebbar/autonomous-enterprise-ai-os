"""Upgrade 12 safety and integration tests. All tests use local fixtures; zero HF calls."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.connectors import build_default_connector_registry
from aeai_os.data.sources import DataSourceRegistry
from aeai_os.monitoring.engine import evaluate_thresholds, execute_claim
from aeai_os.monitoring.store import MonitorStore
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.settings import AppSettings
from aeai_os.storage import LocalArtifactStore


def store(tmp_path):
    return MonitorStore(tmp_path / "monitors.db")


def test_store_create_paused_and_survives_restart(tmp_path):
    s = store(tmp_path)
    created = s.create(
        organization_id="one",
        workspace_id="main",
        name="Daily risk",
        task="Detect unusual procurement activity",
        source_id="data-1",
        interval="daily",
    )
    assert created["enabled"] is False
    assert not s.claim()
    reopened = store(tmp_path)
    assert reopened.get(created["id"], "one", "main")["name"] == "Daily risk"
    assert reopened.get(created["id"], "two", "main") is None
    assert reopened.list("two", "main") == []


def test_claim_once_across_connections_and_trigger(tmp_path):
    s = store(tmp_path)
    entry = s.create(
        organization_id="one",
        workspace_id="main",
        name="Daily risk",
        task="Detect unusual procurement activity",
        source_id="data-1",
        interval="daily",
    )
    assert s.set_enabled(entry["id"], "one", "main", True)
    first = s.claim()
    assert len(first) == 1
    assert store(tmp_path).claim() == []
    s.finish(first[0], status="skipped")
    assert s.trigger(entry["id"], "one", "main")
    next_job = store(tmp_path).claim()
    assert next_job[0]["force_once"] is True
    assert s.history(entry["id"], "one", "main")[0]["status"] == "running"
    assert s.history(entry["id"], "other", "main") == []


def test_alert_review_and_workspace_boundary(tmp_path):
    s = store(tmp_path)
    monitor = s.create(
        organization_id="one",
        workspace_id="main",
        name="Daily risk",
        task="Detect unusual procurement activity",
        source_id="data-1",
        interval="daily",
    )
    s.set_enabled(monitor["id"], "one", "main", True)
    claim = s.claim()[0]
    s.create_alert(
        claim,
        rule="anomalies",
        severity="high",
        title="Review anomalies",
        description="Saved analysis exceeded threshold",
        evidence={"anomaly_count": 4},
        run_id="r_1",
    )
    alert = s.alerts("one", "main")[0]
    assert s.alerts("two", "main") == []
    assert not s.update_alert(alert["id"], "two", "main", "resolved")
    assert s.update_alert(alert["id"], "one", "main", "acknowledged")
    assert s.alerts("one", "main")[0]["status"] == "acknowledged"
    assert s.summary("one", "main")["open_alerts"] == 0
    with pytest.raises(ValueError):
        s.update_alert(alert["id"], "one", "main", "invalid")


def test_thresholds_are_grounded_and_no_fake_baseline(tmp_path):
    monitor = {"anomaly_limit": 2, "minimum_completeness": 0.9, "spend_change_pct": 20}
    first = evaluate_thresholds(
        monitor, {"anomaly_count": 3, "completeness": 0.8, "total_spend": 500}, None
    )
    assert {a["rule"] for a in first} == {"anomalies", "completeness"}
    second = evaluate_thresholds(
        monitor, {"anomaly_count": 0, "total_spend": 120}, {"total_spend": 100}
    )
    assert [a["rule"] for a in second] == ["spend_change"]
    assert second[0]["evidence"]["change_pct"] == 20.0


def test_api_requires_registered_source_and_explicit_enable(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitoring.db"))
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    assert client.get("/monitoring/summary").status_code == 200
    body = {
        "name": "Risk watch",
        "task": "Investigate supplier anomalies and trends",
        "source_id": "not-found",
        "interval": "daily",
    }
    assert client.post("/monitoring/monitors", json=body).status_code == 404
    csv_file = tmp_path / "data.csv"
    csv_file.write_text(
        "supplier,category,spend_amount,invoice_date\nA,IT,120,2026-01-01\n", encoding="utf8"
    )
    created = client.post(
        "/data-sources",
        json={
            "id": "risk-src",
            "name": "Risk Data",
            "source_type": "local_file",
            "dataset_uri": str(csv_file),
            "owner": "test",
        },
    )
    assert created.status_code == 201, created.text
    body["source_id"] = "risk-src"
    response = client.post("/monitoring/monitors", json=body)
    assert response.status_code == 201, response.text
    monitor = response.json()
    assert not monitor["enabled"]
    assert client.post(f"/monitoring/monitors/{monitor['id']}/run-now").status_code == 409
    assert (
        client.patch(
            f"/monitoring/monitors/{monitor['id']}/enabled", json={"enabled": True}
        ).status_code
        == 200
    )
    assert client.post(f"/monitoring/monitors/{monitor['id']}/run-now").status_code == 202
    assert len(client.get("/monitoring/monitors").json()) == 1
    assert client.get("/monitoring/alerts").json() == []
    assert (
        client.patch("/monitoring/alerts/unknown", json={"status": "resolved"}).status_code == 404
    )
    assert (
        client.post("/monitoring/monitors", json={**body, "ai_escalation": True}).status_code == 422
    )


def test_worker_reuses_unchanged_data_without_spending_or_extra_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    repo = InMemoryRunRepository()
    s = store(tmp_path)
    csv_file = tmp_path / "input.csv"
    csv_file.write_text(Path("examples/procurement_demo.csv").read_text(), encoding="utf8")
    registry = DataSourceRegistry(
        connector_registry=build_default_connector_registry(AppSettings())
    )
    registry.register(
        data_source_id="test-procurement",
        name="Procurement CSV",
        source_type="local_file",
        dataset_uri=str(csv_file),
        owner="test",
    )
    mon = s.create(
        organization_id="local-org",
        workspace_id="default",
        name="Daily procurement",
        task="Analyze procurement spending and supplier anomalies over time",
        source_id="test-procurement",
        interval="daily",
        anomaly_limit=1,
    )
    s.set_enabled(mon["id"], "local-org", "default", True)
    claim = s.claim()[0]
    actual = execute_claim(
        claim,
        store=s,
        registry=registry,
        repository=repo,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        artifact_root=tmp_path / "artifacts",
    )
    assert actual["status"] == "completed", actual
    assert repo.get_run(actual["run_id"]).status == "completed"
    assert actual["metrics"]["total_spend"] == 165962.5
    assert len(s.history(mon["id"], "local-org", "default")) == 1
    assert s.alerts("local-org", "default")
    s.trigger(mon["id"], "local-org", "default")
    # Manual trigger forces a run even without changes; normal schedule skips it.
    forced = s.claim()[0]
    assert forced["force_once"]
    s.finish(forced, status="skipped")
    # Manually simulate a normal due poll for unchanged fingerprint.
    with s._connect() as db:
        db.execute(
            "UPDATE monitors SET next_due_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", mon["id"])
        )
    ordinary = s.claim()[0]
    skipped = execute_claim(
        ordinary,
        store=s,
        registry=registry,
        repository=repo,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        artifact_root=tmp_path / "artifacts",
    )
    assert skipped["status"] == "skipped"
    assert len(repo.list_runs()) == 1


def test_worker_failure_is_recorded_and_not_replayed(tmp_path):
    s = store(tmp_path)
    mon = s.create(
        organization_id="local-org",
        workspace_id="default",
        name="Invalid monitor",
        task="Review records for anomalous patterns",
        source_id="nonexistent",
        interval="daily",
    )
    s.set_enabled(mon["id"], "local-org", "default", True)
    claim = s.claim()[0]
    result = execute_claim(
        claim,
        store=s,
        registry=DataSourceRegistry(connector_registry=object()),
        repository=InMemoryRunRepository(),
        artifact_store=object(),
        artifact_root=tmp_path,
    )
    assert result["status"] == "failed"
    assert s.claim() == []
    assert s.alerts("local-org", "default")[0]["rule"] == "execution_failure"


def test_sqlite_monitor_store_and_run_repo_persist_independently(tmp_path):
    s = store(tmp_path)
    monitor = s.create(
        organization_id="one",
        workspace_id="default",
        name="Daily quality",
        task="Check quality of procurement data",
        source_id="src",
        interval="daily",
    )
    r = SQLAlchemyRunRepository.from_url(f"sqlite:///{tmp_path / 'runs.db'}", create_schema=True)
    run = r.create_run(
        "Investigate supplier risks", metadata={"organization_id": "one", "workspace_id": "default"}
    )
    assert store(tmp_path).get(monitor["id"], "one", "default") is not None
    r2 = SQLAlchemyRunRepository.from_url(f"sqlite:///{tmp_path / 'runs.db'}")
    assert r2.get_run(run.id).id == run.id


def test_s3_allowlist_blocks_unapproved_and_query_urls(monkeypatch):
    from aeai_os.monitoring.engine import allowed_s3_reference

    monkeypatch.setenv("AEAI_MONITOR_S3_ALLOWED_BUCKETS", "trusted-data")
    assert allowed_s3_reference("s3://trusted-data/exports/procurement.csv") == (
        "trusted-data",
        "exports/procurement.csv",
    )
    for uri in (
        "s3://another-bucket/file.csv",
        "https://trusted-data/file.csv",
        "s3://trusted-data/x.csv?credentials=secret",
        "s3://trusted-data/../private.csv",
        "s3://trusted-data/receipt.pdf",
    ):
        with pytest.raises(ValueError):
            allowed_s3_reference(uri)


def test_read_only_s3_snapshot_is_bounded_and_never_uploads(tmp_path, monkeypatch):
    import io
    import sys
    import types

    from aeai_os.monitoring.engine import download_s3_snapshot, fingerprint_source

    monkeypatch.setenv("AEAI_MONITOR_S3_ALLOWED_BUCKETS", "trusted-data")
    payload = b"supplier,category,spend_amount\nA,Office,15\nB,Office,12\n"
    calls = []

    class Client:
        def head_object(self, **kwargs):
            calls.append(("head", kwargs))
            return {"ContentLength": len(payload)}

        def get_object(self, **kwargs):
            calls.append(("get", kwargs))
            return {"Body": io.BytesIO(payload)}

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: Client()))
    snapshot = download_s3_snapshot("s3://trusted-data/exports/test.csv", tmp_path)
    assert Path(snapshot.dataset_uri).read_bytes() == payload
    assert fingerprint_source(snapshot)
    assert [operation for operation, _ in calls] == ["head", "get"]
    assert not any("put" in operation for operation, _ in calls)


def test_api_s3_creation_requires_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "mon.db"))
    monkeypatch.setenv("AEAI_MONITOR_S3_ALLOWED_BUCKETS", "trusted-data")
    client = TestClient(
        create_app(repository=InMemoryRunRepository(), artifact_root=tmp_path / "artifacts")
    )
    body = {
        "name": "S3 monitor",
        "task": "Review procurement transaction trends",
        "source_id": "s3://trusted-data/incoming/data.csv",
        "interval": "weekly",
    }
    assert client.post("/monitoring/monitors", json=body).status_code == 201
    assert (
        client.post(
            "/monitoring/monitors", json={**body, "source_id": "s3://private-data/file.csv"}
        ).status_code
        == 422
    )


def test_optional_ai_escalation_has_two_optins_and_no_background_calls(monkeypatch):
    from aeai_os.monitoring.engine import optional_ai_review

    monitor = {"ai_escalation": True}
    alerts = [{"rule": "anomalies", "severity": "high"}]
    monkeypatch.delenv("AEAI_MONITOR_AI_ESCALATION_ENABLED", raising=False)
    assert optional_ai_review(monitor, alerts, {"anomaly_count": 2}, "dispatch_1") == {}
    monkeypatch.setenv("AEAI_MONITOR_AI_ESCALATION_ENABLED", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    result = optional_ai_review(monitor, alerts, {"anomaly_count": 2}, "dispatch_1")
    assert result["status"] == "skipped"


def test_opted_in_ai_review_is_bounded_and_qualitative(monkeypatch, tmp_path):
    from aeai_os.llm import gateway
    from aeai_os.monitoring.engine import optional_ai_review

    calls = []
    monkeypatch.setenv("AEAI_MONITOR_AI_ESCALATION_ENABLED", "true")
    monkeypatch.setenv("HF_TOKEN", "hf_mock_not_real")
    monkeypatch.setenv("AEAI_LLM_USAGE_LEDGER_PATH", str(tmp_path / "usage.jsonl"))

    def generate(self, **kwargs):
        calls.append(kwargs)
        assert "supplier" not in kwargs["input_text"].lower()
        assert kwargs["max_output_tokens"] == 500
        return {
            "interpretation": "A significant pattern warrants additional review.",
            "recommended_next_step": "Ask a procurement owner to validate the underlying evidence.",
        }

    monkeypatch.setattr(gateway.HuggingFaceChatGateway, "generate", generate)
    monitor = {"ai_escalation": True}
    review = optional_ai_review(
        monitor, [{"rule": "anomalies"}], {"anomaly_count": 7, "total_spend": 500}, "dispatch_mock"
    )
    assert review["status"] == "created"
    assert len(calls) == 1
    assert review["model"] == "Qwen/Qwen3-32B"
    assert (
        optional_ai_review({"ai_escalation": False}, [{"rule": "anomalies"}], {}, "dispatch_other")
        == {}
    )


def test_sqlalchemy_scheduled_run_survives_reopening(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    input_file = tmp_path / "input.csv"
    input_file.write_bytes(Path("examples/procurement_demo.csv").read_bytes())
    source_catalog = tmp_path / "sources.json"
    registry = DataSourceRegistry(
        connector_registry=object(), env={"AEAI_LOCAL_SOURCE_CATALOG_PATH": str(source_catalog)}
    )
    registry.register(
        data_source_id="scheduled-input",
        name="Input",
        source_type="local_file",
        dataset_uri=str(input_file),
        owner="local",
    )
    restarted = DataSourceRegistry(
        connector_registry=object(), env={"AEAI_LOCAL_SOURCE_CATALOG_PATH": str(source_catalog)}
    )
    s = store(tmp_path)
    mon = s.create(
        organization_id="local-org",
        workspace_id="default",
        name="SQL saved monitor",
        task="Investigate supplier spending trends",
        source_id="scheduled-input",
        interval="daily",
    )
    s.set_enabled(mon["id"], "local-org", "default", True)
    db = f"sqlite:///{tmp_path / 'workspace.db'}"
    repo = SQLAlchemyRunRepository.from_url(db, create_schema=True)
    result = execute_claim(
        s.claim()[0],
        store=s,
        registry=restarted,
        repository=repo,
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        artifact_root=tmp_path / "artifacts",
    )
    assert result["status"] == "completed", result
    after = SQLAlchemyRunRepository.from_url(db)
    assert after.get_run(result["run_id"]).status == "completed"
    assert (
        store(tmp_path).history(mon["id"], "local-org", "default")[0]["run_id"] == result["run_id"]
    )

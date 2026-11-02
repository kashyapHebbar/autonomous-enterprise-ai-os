"""Upgrade 12.5 offline operational tests — no paid LLM calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.operations.heartbeat import read_heartbeat, write_heartbeat
from aeai_os.runs.repository import InMemoryRunRepository
from scripts.launch_ai_os import local_environment


def test_heartbeat_online_and_stale(tmp_path):
    path = tmp_path / "heartbeat.json"
    assert read_heartbeat(path=path)["online"] is False
    write_heartbeat(worker_id="test", active=True, path=path)
    assert read_heartbeat(path=path)["online"] is True
    assert read_heartbeat(path=path)["active"] is True
    previous = json.loads(path.read_text())
    previous["last_seen"] = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    path.write_text(json.dumps(previous))
    assert read_heartbeat(path=path)["online"] is False
    assert read_heartbeat(path=path)["active"] is False


def test_heartbeat_rejects_symlink(tmp_path):
    target = tmp_path / "real.json"
    target.write_text("{}")
    fake = tmp_path / "fake.json"
    fake.symlink_to(target)
    assert not read_heartbeat(path=fake)["online"]
    try:
        write_heartbeat(worker_id="a", active=False, path=fake)
        raise AssertionError("symlink should not be writable")
    except ValueError:
        pass


def test_launcher_sets_shared_async_database_without_echoing_secrets():
    env = local_environment({"HF_TOKEN": "hf_dummy_test_only", "AEAI_LLM_ENABLED": "true"})
    assert env["AEAI_RUN_REPOSITORY_BACKEND"] == "sqlalchemy"
    assert env["AEAI_WORKFLOW_EXECUTION_MODE"] == "async"
    assert env["AEAI_DATABASE_URL"].startswith("sqlite:")
    assert env["HF_TOKEN"] == "hf_dummy_test_only"
    assert env["AEAI_LLM_ENABLED"] == "true"


def test_operations_memory_mode_and_status_are_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitors.db"))
    repo = InMemoryRunRepository()
    app = create_app(repository=repo, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    info = client.get("/operations/status")
    assert info.status_code == 200, info.text
    data = info.json()
    assert data["workflow_worker"]["mode"] == "inline"
    assert data["workflow_worker"]["online"] is True
    assert data["actions"]["arbitrary_shell"] is False
    assert data["queue"]["queued"] == 0
    assert "HF_TOKEN" not in info.text


def test_operations_reports_real_queue_and_filters_other_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_MONITOR_DB_PATH", str(tmp_path / "monitors.db"))
    repo = InMemoryRunRepository()
    visible = repo.create_run(
        "Analyze public government procurement data",
        metadata={"organization_id": "local-org", "workspace_id": "default"},
    )
    hidden = repo.create_run(
        "Sensitive other-company analysis",
        metadata={"organization_id": "other-org", "workspace_id": "default"},
    )
    repo.enqueue_workflow_job(run_id=visible.id, workflow_name="dynamic_analysis")
    repo.enqueue_workflow_job(run_id=hidden.id, workflow_name="dynamic_analysis")
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    info = client.get("/operations/status").json()
    assert info["queue"]["queued"] == 1
    assert len(info["jobs"]) == 1
    assert info["jobs"][0]["run_id"] == visible.id
    assert hidden.id not in str(info)
    assert "Sensitive other-company" not in str(info)


def test_reconstructed_frontend_and_process_contracts():
    root = Path(__file__).resolve().parents[1]
    assert "scripts/launch_ai_os.py" in (root / "scripts/start_persistent_local.sh").read_text()
    assert "$(PYTHON) scripts/launch_ai_os.py" in (root / "Makefile").read_text()
    assert "/operations/status" in (root / "frontend/src/api.ts").read_text()
    assert "retryDeadLetter" in (root / "frontend/src/pages/Operations.tsx").read_text()
    assert "Operations Center" in (root / "frontend/src/components/Layout.tsx").read_text()
    assert "build_operations_router" in (root / "src/aeai_os/api/app.py").read_text()
    assert "monitoring-worker:" in (root / "docker-compose.yml").read_text()

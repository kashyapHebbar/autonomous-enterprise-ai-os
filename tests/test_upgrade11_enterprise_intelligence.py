"""Upgrade 11 regression: no paid inference, no external HTTP requests."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aeai_os.agents.run_questions import model_question_context
from aeai_os.api.app import create_app
from aeai_os.data.sources import DataSourceRegistry
from aeai_os.intelligence.overview import build_overview, workspace_health
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.schemas.enums import RunStatus
from aeai_os.settings import AppSettings


class User:
    def __init__(self, org="local-org"):
        self.org = org

    def can_access(self, org, workspace):
        return org == self.org and workspace == "default"


def test_local_source_catalog_survives_restart(tmp_path):
    catalog = tmp_path / "catalog.json"
    source_file = tmp_path / "procurement.csv"
    source_file.write_text("supplier,amount\nA,100\n", encoding="utf8")
    env = {"AEAI_LOCAL_SOURCE_CATALOG_PATH": str(catalog)}
    first = DataSourceRegistry(connector_registry=object(), env=env)
    record = first.register(
        data_source_id="demo-data",
        name="Test data",
        source_type="local_file",
        dataset_uri=str(source_file),
        owner="test-owner",
    )
    assert record.id == "demo-data"
    assert json.loads(catalog.read_text())["version"] == 1
    assert os.stat(catalog).st_mode & 0o077 == 0
    second = DataSourceRegistry(connector_registry=object(), env=env)
    assert second.get("demo-data").dataset_uri == str(source_file)
    assert second.get("demo-data").metadata == {}
    assert second.validate("demo-data").status == "ok"


def test_local_source_catalog_rejects_symlink_and_corrupt_json(tmp_path):
    valid = tmp_path / "good.json"
    valid.write_text('{"version":1,"sources":[]}', encoding="utf8")
    linked = tmp_path / "linked.json"
    linked.symlink_to(valid)
    with pytest.raises(ValueError):
        DataSourceRegistry(
            connector_registry=object(), env={"AEAI_LOCAL_SOURCE_CATALOG_PATH": str(linked)}
        )
    bad = tmp_path / "bad.json"
    bad.write_text("{broken", encoding="utf8")
    with pytest.raises(ValueError):
        DataSourceRegistry(
            connector_registry=object(), env={"AEAI_LOCAL_SOURCE_CATALOG_PATH": str(bad)}
        )


def test_sqlite_workspace_runs_survive_recreation(tmp_path):
    db = f"sqlite+pysqlite:///{tmp_path / 'runs.db'}"
    first = SQLAlchemyRunRepository.from_url(db, create_schema=True)
    run = first.create_run(
        "Review the local source and explain supplier risk",
        metadata={"organization_id": "local-org", "workspace_id": "default"},
    )
    first.update_status(run.id, RunStatus.FAILED, error_summary="Test failure")
    second = SQLAlchemyRunRepository.from_url(db, create_schema=False)
    assert second.get_run(run.id).status == RunStatus.FAILED
    assert (
        workspace_health(second, User(), repository_backend="sqlalchemy")["persistent_runs"] is True
    )


def test_memory_mode_has_explicit_nonpersistent_warning():
    result = workspace_health(InMemoryRunRepository(), User(), repository_backend="memory")
    assert result["persistent_runs"] is False
    assert result["auto_recovery_enabled"] is False


def test_stale_runs_are_only_flagged_not_replayed():
    repo = InMemoryRunRepository()
    run = repo.create_run(
        "Investigate stored procurement history", metadata={"organization_id": "local-org"}
    )
    repo.update_status(run.id, RunStatus.RUNNING)
    # Seed a stale record in this in-memory test without triggering any execution.
    repo._runs[run.id] = replace(
        repo._runs[run.id], updated_at=datetime.now(UTC) - timedelta(hours=2)
    )
    state = workspace_health(repo, User(), repository_backend="memory")
    assert [x["run_id"] for x in state["stale_runs"]] == [run.id]
    assert state["auto_recovery_enabled"] is False
    assert len(repo.list_runs()) == 1


def test_intelligence_overview_reads_real_completed_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    assert client.get("/investigations/intelligence-overview").json()["latest"] is None
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spending in test data",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    complete = client.post(f"/runs/{run['id']}/execute")
    assert complete.status_code == 200, complete.text
    response = client.get("/investigations/intelligence-overview")
    assert response.status_code == 200
    overview = response.json()
    assert overview["completed_runs"] == 1
    assert overview["analyzed_runs"] == 1
    assert overview["latest"]["run_id"] == run["id"]
    assert overview["latest"]["figures"]["total_spend"] == 165962.5
    assert overview["latest"]["artifact_id"]
    assert overview["latest"]["trend"]
    assert overview["latest"]["recommendations"]
    assert "must not be added" in overview["note"]
    assert client.get("/investigations/workspace-health").json()["persistent_runs"] is False


def test_overview_is_tenant_scoped(tmp_path, monkeypatch):
    repo = InMemoryRunRepository()
    repo.create_run(
        "Analyze private financial dataset",
        metadata={"organization_id": "other-org", "workspace_id": "default"},
    )
    assert build_overview(repo, object(), User())["completed_runs"] == 0
    assert workspace_health(repo, User(), repository_backend="memory")["failed_runs"] == []


def test_conversation_history_is_bounded_and_does_not_include_artifact_ids():
    evidence = [
        {
            "id": "evidence_key_figures",
            "label": "Verified figures",
            "facts": {"anomaly_count": 3},
            "source_artifact_id": "secret_artifact_id",
            "source_paths": ["kpis.anomaly_count"],
        }
    ]
    history = [{"question": f"Question {i}", "answer": "Needs verification"} for i in range(5)]
    context = json.loads(model_question_context("What changed?", evidence, history))
    assert len(context["recent_conversation_for_context_only"]) == 3
    assert context["recent_conversation_for_context_only"][0]["question"] == "Question 2"
    assert "secret_artifact_id" not in json.dumps(context)


def test_duplicate_saved_questions_reuse_answer_without_another_llm_call(tmp_path, monkeypatch):
    from aeai_os.api import runs as run_api

    class Fake:
        model = "Qwen/Qwen3-32B"

        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            references = json.loads(kwargs["input_text"])["approved_verified_evidence"]
            return {
                "answer": "Saved signals warrant review with the appropriate business owner.",
                "evidence_ids": [references[0]["id"]],
                "limitations": [],
            }

    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    monkeypatch.setenv("AEAI_LLM_ENABLED", "false")
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze supplier spending",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    assert client.post(f"/runs/{run['id']}/execute").status_code == 200
    fake = Fake()
    config = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock_only",
        run_questions_enabled=True,
        llm_usage_ledger_path=str(tmp_path / "usage.jsonl"),
    )
    monkeypatch.setattr(run_api, "get_settings", lambda: config)
    monkeypatch.setattr(run_api, "build_llm_gateway", lambda **_kwargs: fake)
    first = client.post(
        f"/runs/{run['id']}/questions", json={"question": "Which suppliers need review?"}
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/runs/{run['id']}/questions", json={"question": "  WHICH suppliers need review?  "}
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert len(fake.calls) == 1
    assert len(client.get(f"/runs/{run['id']}/questions").json()) == 1
    followup = client.post(
        f"/runs/{run['id']}/questions",
        json={"question": "What should happen after reviewing these suppliers?"},
    )
    assert followup.status_code == 200, followup.text
    ctx = json.loads(fake.calls[1]["input_text"])
    assert (
        ctx["recent_conversation_for_context_only"][0]["question"] == "Which suppliers need review?"
    )
    assert len(fake.calls) == 2


def test_new_cross_segment_tools_are_aggregated_and_privacy_bounded():
    from aeai_os.agents.analyst_tools import _eligible_plan, run_approved_tool

    rows = [
        ("A", "Equipment", "Engineering", "2026-01", 100.0),
        ("A", "Equipment", "Engineering", "2026-01", 200.0),
        ("B", "Travel", "Finance", "2026-02", 50.0),
        ("B", "Travel", "Finance", "2026-02", 40.0),
        ("C", "Misc", "Sales", "2026-03", 12.0),  # must be suppressed
    ]
    dataset = {
        "rows": rows,
        "months": ["2026-01", "2026-02", "2026-03"],
        "suppliers": ["A", "B", "C"],
        "categories": ["Equipment", "Travel", "Misc"],
        "departments": ["Engineering", "Finance", "Sales"],
    }
    for tool in (
        "supplier_category_breakdown",
        "category_monthly_breakdown",
        "department_monthly_breakdown",
    ):
        plan = {
            "tool": tool,
            "supplier": None,
            "first_month": None,
            "last_month": None,
            "rationale": "Check variation.",
        }
        checked = _eligible_plan(plan, dataset)
        result = run_approved_tool(checked, dataset, "USD")
        assert len(result["points"]) == 2
        assert all(item["transactions"] >= 2 for item in result["points"])
        assert result["verified_total"] == 390.0
        assert all(
            "Misc" not in item["label"] and "Sales" not in item["label"]
            for item in result["points"]
        )
        assert "suppressed" in " ".join(result["limitations"])


def test_cached_answer_available_after_model_disabled(tmp_path, monkeypatch):
    from aeai_os.api import runs as run_api

    class Provider:
        model = "Qwen/Qwen3-32B"

        def __init__(self):
            self.calls = 0

        def generate(self, **kwargs):
            self.calls += 1
            evidence = json.loads(kwargs["input_text"])["approved_verified_evidence"]
            return {
                "answer": "Review the verified spending signals before drawing conclusions.",
                "evidence_ids": [evidence[0]["id"]],
                "limitations": [],
            }

    monkeypatch.setenv("AEAI_DYNAMIC_REASONING_ENABLED", "false")
    monkeypatch.setenv("AEAI_REASONING_FOLLOWUPS_ENABLED", "false")
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze supplier spending",
            "dataset_uri": str(Path("examples/procurement_demo.csv").resolve()),
        },
    ).json()
    assert client.post(f"/runs/{run['id']}/execute").status_code == 200
    fake = Provider()
    allowed = AppSettings(
        llm_enabled=True,
        llm_api_key="hf_mock",
        run_questions_enabled=True,
        llm_usage_ledger_path=str(tmp_path / "ledger.jsonl"),
    )
    monkeypatch.setattr(run_api, "get_settings", lambda: allowed)
    monkeypatch.setattr(run_api, "build_llm_gateway", lambda **kwargs: fake)
    first = client.post(
        f"/runs/{run['id']}/questions", json={"question": "What should managers review first?"}
    )
    assert first.status_code == 200, first.text
    monkeypatch.setattr(
        run_api, "get_settings", lambda: replace(allowed, llm_enabled=False, llm_api_key="")
    )
    repeat = client.post(
        f"/runs/{run['id']}/questions", json={"question": "What should managers review first?"}
    )
    assert repeat.status_code == 200
    assert repeat.json()["id"] == first.json()["id"]
    assert fake.calls == 1


def test_local_workspace_backup_uses_sqlite_snapshot(tmp_path):
    from runpy import run_path
    from zipfile import ZipFile

    root = tmp_path / "project"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    repo = SQLAlchemyRunRepository.from_url(
        f"sqlite+pysqlite:///{artifacts / 'aeai-local-runs.db'}", create_schema=True
    )
    sample = repo.create_run("Test durable workspace backups")
    (artifacts / "aeai-local-sources.json").write_text(
        '{"version":1,"sources":[]}', encoding="utf8"
    )
    backup_module = run_path(str(Path("scripts/backup_local_workspace.py").resolve()))
    destination = tmp_path / "backup.zip"
    assert backup_module["backup"](root, destination) == destination
    with ZipFile(destination) as archive:
        assert {"workspace/runs.db", "workspace/local-data-sources.json"} == set(archive.namelist())
        restored = tmp_path / "restored.sqlite"
        restored.write_bytes(archive.read("workspace/runs.db"))
    new_repo = SQLAlchemyRunRepository.from_url(
        f"sqlite+pysqlite:///{restored}", create_schema=False
    )
    assert new_repo.get_run(sample.id).task == "Test durable workspace backups"
    assert destination.stat().st_mode & 0o077 == 0

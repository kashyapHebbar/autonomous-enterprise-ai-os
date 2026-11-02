"""Regression tests for the general-purpose async queue and live execution stream."""

from pathlib import Path

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType, RunStatus, WorkflowJobStatus
from aeai_os.storage import LocalArtifactStore
from aeai_os.workflows.worker import WorkflowWorker, enqueue_dynamic_workflow


def _csv(tmp_path: Path) -> Path:
    path = tmp_path / "regional_sales.csv"
    path.write_text(
        "order_id,order_date,region,product,revenue,units\n"
        "1,2026-01-01,North,Widget,120,4\n"
        "2,2026-02-01,South,Gadget,350,7\n"
        "3,2026-03-01,North,Gadget,200,5\n",
        encoding="utf-8",
    )
    return path


def test_async_api_completes_generic_workflow_in_local_memory_mode(tmp_path):
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze regional sales performance and trends",
            "dataset_uri": str(_csv(tmp_path)),
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/async")
    assert response.status_code == 202
    assert response.json()["workflow_name"] == "dynamic_analysis"
    assert response.json()["max_attempts"] == 1

    assert client.get(f"/runs/{run['id']}").json()["status"] == "completed"
    assert client.get(f"/runs/{run['id']}/workflow-jobs").json()[0]["status"] == "completed"
    assert len(client.get(f"/runs/{run['id']}/graph-nodes").json()) == 5
    assert len(client.get(f"/runs/{run['id']}/artifacts").json()) > 1

    duplicate = client.post(f"/runs/{run['id']}/execute/async")
    assert duplicate.status_code == 409

    stream = client.get(f"/runs/{run['id']}/stream")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert '"status":"completed"' in stream.text
    assert "event: finished" in stream.text


def test_async_api_rejects_missing_dataset_without_creating_job(tmp_path):
    repo = InMemoryRunRepository()
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    run = client.post("/runs", json={"task": "Analyze something"}).json()
    response = client.post(f"/runs/{run['id']}/execute/async")
    assert response.status_code == 400
    assert repo.list_workflow_jobs(run_id=run["id"]) == []


def test_worker_can_claim_and_execute_dynamic_warehouse_independent_job(tmp_path):
    repo = InMemoryRunRepository()
    run = repo.create_run("Analyze sales by region and detect outliers")
    repo.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(_csv(tmp_path)),
        metadata={"source": "test", "format": "csv"},
    )
    job = enqueue_dynamic_workflow(repo, run.id)
    assert repo.get_run(run.id).status == RunStatus.QUEUED
    worker = WorkflowWorker(
        repository=repo,
        artifact_root=tmp_path / "artifacts",
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
    )
    result = worker.process_next_job()
    assert result is not None
    assert result.id == job.id
    assert result.status == WorkflowJobStatus.COMPLETED
    assert repo.get_run(run.id).status == RunStatus.COMPLETED
    assert worker.process_next_job() is None


def test_stream_requires_read_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_MODE", "token")
    monkeypatch.setenv(
        "AEAI_AUTH_TOKEN_PROFILES",
        "viewer-token=viewer-1|Viewer|viewer;operator-token=operator-1|Operator|operator",
    )
    repo = InMemoryRunRepository()
    run = repo.create_run(
        "Private analysis", metadata={"organization_id": "local-org", "workspace_id": "default"}
    )
    client = TestClient(create_app(repository=repo, artifact_root=tmp_path / "artifacts"))
    response = client.get(f"/runs/{run.id}/stream")
    assert response.status_code == 401


def test_sqlalchemy_api_queues_until_external_worker_claims_job(tmp_path):
    from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository

    repo = SQLAlchemyRunRepository.from_url(
        f"sqlite+pysqlite:///{tmp_path / 'runs.db'}", create_schema=True
    )
    app = create_app(repository=repo, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = client.post(
        "/runs",
        json={"task": "Analyze regional sales performance", "dataset_uri": str(_csv(tmp_path))},
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/async")
    assert response.status_code == 202
    assert repo.get_run(run["id"]).status == RunStatus.QUEUED
    assert repo.get_workflow_job(response.json()["id"]).status == WorkflowJobStatus.QUEUED

    # Same DB, a separate instance, as an external worker would use.
    worker_repo = SQLAlchemyRunRepository.from_url(f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    worker = WorkflowWorker(
        repository=worker_repo,
        artifact_root=tmp_path / "artifacts",
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
    )
    result = worker.process_next_job()
    assert result is not None and result.status == WorkflowJobStatus.COMPLETED
    assert repo.get_run(run["id"]).status == RunStatus.COMPLETED

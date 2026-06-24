from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.models import EvaluationResultRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType


def write_procurement_fixture(path):
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-05,100,IT",
                "Acme,Software,2026-01-06,100,IT",
                "Zenith,Hardware,2026-02-01,200,Operations",
                "Acme,Cloud,2026-02-10,1000,IT",
                "Tiny,Office,2026-03-01,10,Finance",
            ]
        ),
        encoding="utf-8",
    )


def build_client(tmp_path):
    app = create_app(repository=InMemoryRunRepository(), artifact_root=tmp_path / "artifacts")
    return TestClient(app)


def test_app_can_select_sqlalchemy_run_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_BACKEND", "sqlalchemy")
    monkeypatch.setenv("AEAI_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    app = create_app(artifact_root=tmp_path / "artifacts")
    client = TestClient(app)

    response = client.post("/runs", json={"task": "Analyze procurement spend."})

    assert app.state.run_repository.__class__.__name__ == "SQLAlchemyRunRepository"
    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_create_run_and_fetch_status(tmp_path):
    client = build_client(tmp_path)

    response = client.post(
        "/runs",
        json={"task": "Analyze this procurement dataset and create a dashboard."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("run_")
    assert body["status"] == "pending"
    assert body["task"] == "Analyze this procurement dataset and create a dashboard."
    assert body["artifacts"] == []
    assert len(body["trace_id"]) == 32
    assert response.headers["x-trace-id"] == body["trace_id"]

    get_response = client.get(f"/runs/{body['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


def test_create_run_rejects_blank_task(tmp_path):
    client = build_client(tmp_path)

    response = client.post("/runs", json={"task": "  "})

    assert response.status_code == 422


def test_attach_dataset_reference_and_list_artifacts(tmp_path):
    client = build_client(tmp_path)
    run = client.post("/runs", json={"task": "Analyze procurement spend."}).json()

    response = client.post(
        f"/runs/{run['id']}/datasets/reference",
        json={"uri": "s3://bucket/procurement.csv", "format": "csv"},
    )

    assert response.status_code == 201
    artifact = response.json()
    assert artifact["type"] == "dataset"
    assert artifact["metadata"]["source"] == "reference"

    artifacts = client.get(f"/runs/{run['id']}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()[0]["id"] == artifact["id"]


def test_get_artifact_and_lineage(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Analyze procurement spend.")
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(tmp_path / "procurement.csv"),
        metadata={"source": "test", "format": "csv"},
    )
    report = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri=str(tmp_path / "report.md"),
        metadata={"source": "test", "format": "markdown"},
        source_artifact_ids=[dataset.id],
        producer_node_id="report",
    )

    artifact_response = client.get(f"/runs/{run.id}/artifacts/{report.id}")
    lineage_response = client.get(f"/runs/{run.id}/artifacts/{report.id}/lineage")
    missing_response = client.get(f"/runs/{run.id}/artifacts/missing")

    assert artifact_response.status_code == 200
    assert artifact_response.json()["id"] == report.id
    assert artifact_response.json()["producer_node_id"] == "report"
    assert lineage_response.status_code == 200
    assert lineage_response.json()["root_artifact"]["id"] == report.id
    assert lineage_response.json()["upstream_artifacts"][0]["id"] == dataset.id
    assert lineage_response.json()["edges"] == [
        {"source_artifact_id": dataset.id, "target_artifact_id": report.id}
    ]
    assert missing_response.status_code == 404


def test_run_detail_and_evaluations_endpoint_include_failed_evaluation(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Analyze procurement spend.")
    report = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri=str(tmp_path / "report.md"),
        metadata={"source": "test", "format": "markdown"},
        producer_node_id="report",
    )
    evaluation = repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_failed",
            run_id=run.id,
            target_artifact_id=report.id,
            score=0.75,
            passed=False,
            checks=[
                {
                    "name": "data_consistency",
                    "passed": False,
                    "score": 0.0,
                    "required": True,
                    "message": "Report total does not match computed KPI total.",
                    "details": {"report_matches": False},
                }
            ],
        )
    )

    detail_response = client.get(f"/runs/{run.id}")
    evaluations_response = client.get(f"/runs/{run.id}/evaluations")
    evaluation_events = [
        event for event in repository.list_events(run.id) if event.event_type == "evaluation"
    ]

    assert detail_response.status_code == 200
    assert detail_response.json()["evaluations"][0]["id"] == evaluation.id
    assert detail_response.json()["evaluations"][0]["passed"] is False
    assert evaluations_response.status_code == 200
    assert evaluations_response.json()[0]["checks"][0]["name"] == "data_consistency"
    assert evaluation_events[0].payload["backend"] == "opentelemetry"
    assert evaluation_events[0].payload["trace_id"] == repository.get_run(run.id).trace_id


def test_metrics_endpoint_exposes_run_artifact_and_evaluation_metrics(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Analyze procurement spend.")
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri=str(tmp_path / "report.md"),
        metadata={"source": "test", "format": "markdown"},
        producer_node_id="report",
    )
    repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_passed",
            run_id=run.id,
            target_artifact_id=None,
            score=0.9,
            passed=True,
            checks=[{"name": "task_completion", "passed": True, "score": 1.0}],
        )
    )

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "aeai_runs_total 1" in response.text
    assert 'aeai_runs_by_status{status="pending"} 1' in response.text
    assert "aeai_artifacts_total 1" in response.text
    assert "aeai_evaluations_total 1" in response.text
    assert "aeai_evaluation_score_average 0.900000" in response.text


def test_execute_procurement_workflow_from_api(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)

    run_response = client.post(
        "/runs",
        json={
            "task": "Analyze this procurement dataset and create a dashboard report.",
            "dataset_uri": str(dataset_path),
        },
    )
    run = run_response.json()

    response = client.post(f"/runs/{run['id']}/execute/procurement")

    body = response.json()
    artifact_types = {artifact["type"] for artifact in body["artifacts"]}
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["trace_id"] == run["trace_id"]
    assert body["completed_node_ids"] == [
        "data_profile",
        "analytics",
        "visualization",
        "report",
        "evaluation",
    ]
    assert body["failed_node_ids"] == []
    assert body["waiting_for_approval_node_id"] is None
    assert {"dashboard", "report", "evaluation"}.issubset(artifact_types)
    assert body["evaluations"][-1]["passed"] is True


def test_execute_procurement_workflow_requires_dataset(tmp_path):
    client = build_client(tmp_path)
    run = client.post(
        "/runs",
        json={"task": "Analyze this procurement dataset and create a dashboard report."},
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/procurement")

    assert response.status_code == 400
    assert "dataset artifact must be attached" in response.json()["detail"]


def test_upload_dataset_rejects_unsupported_file_type(tmp_path):
    client = build_client(tmp_path)
    run = client.post("/runs", json={"task": "Analyze procurement spend."}).json()

    response = client.post(
        f"/runs/{run['id']}/datasets/upload",
        files={"file": ("malware.exe", b"not a dataset", "application/octet-stream")},
    )

    assert response.status_code == 400

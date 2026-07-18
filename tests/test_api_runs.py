import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.agents.registry import build_default_registry
from aeai_os.api.app import create_app
from aeai_os.orchestration.graph import ExecutionGraph, ExecutionNode
from aeai_os.orchestration.service import OrchestratorService, RetryPolicy
from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord, GraphNodeRecord
from aeai_os.runs.repository import InMemoryRunRepository, utc_now
from aeai_os.schemas.enums import (
    AgentEventType,
    ArtifactType,
    GraphNodeStatus,
    RunStatus,
    WorkflowJobStatus,
)
from aeai_os.workflows import build_procurement_orchestrator

AUTH_TOKEN_PROFILES = (
    "viewer-token=viewer-1|Viewer One|viewer;"
    "operator-token=operator-1|Operator One|operator;"
    "reviewer-token=reviewer-1|Reviewer One|reviewer;"
    "approver-token=approver-1|Approver One|approver"
)
VIEWER_HEADERS = {"X-AEAI-API-Key": "viewer-token"}
OPERATOR_HEADERS = {"Authorization": "Bearer operator-token"}
REVIEWER_HEADERS = {"Authorization": "Bearer reviewer-token"}
APPROVER_HEADERS = {"Authorization": "Bearer approver-token"}


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


def write_procurement_sqlite_fixture(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE procurement (
                supplier TEXT,
                category TEXT,
                invoice_date TEXT,
                spend_amount REAL,
                department TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO procurement VALUES (?, ?, ?, ?, ?)",
            [
                ("Acme", "Software", "2026-01-05", 100, "IT"),
                ("Acme", "Software", "2026-01-06", 100, "IT"),
                ("Zenith", "Hardware", "2026-02-01", 200, "Operations"),
                ("Acme", "Cloud", "2026-02-10", 1000, "IT"),
                ("Tiny", "Office", "2026-03-01", 10, "Finance"),
            ],
        )


def build_client(tmp_path):
    app = create_app(repository=InMemoryRunRepository(), artifact_root=tmp_path / "artifacts")
    return TestClient(app)


def seed_waiting_data_profile_run(repository, artifact_root, tmp_path):
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = repository.create_run("Profile procurement data with approval.")
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(dataset_path),
        metadata={"source": "test", "format": "csv"},
    )
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="data_profile",
                agent="data_retrieval",
                task="Profile procurement dataset.",
                required_tools=["snowflake_query"],
                expected_artifacts=["schema_profile", "quality_report"],
                risk="high",
            )
        ],
    )
    result = build_procurement_orchestrator(repository, artifact_root).execute_run(
        run.id, graph
    )
    assert result.waiting_for_approval_node_id == "data_profile"
    return run


def test_auth_disabled_allows_local_run_creation_and_records_local_actor(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)

    response = client.post("/runs", json={"task": "Analyze procurement spend."})

    body = response.json()
    audit_event = next(
        event for event in repository.list_events(body["id"])
        if event.event_type == AgentEventType.AUDIT.value
    )
    assert response.status_code == 201
    assert audit_event.payload["action"] == "run.create"
    assert audit_event.payload["actor"] == {
        "id": "local-dev",
        "name": "Local Developer",
        "roles": ["admin"],
    }


def test_auth_enabled_requires_authenticated_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", AUTH_TOKEN_PROFILES)
    client = build_client(tmp_path)

    response = client.get("/runs")

    assert response.status_code == 401
    assert "Missing bearer token" in response.json()["detail"]


def test_auth_enabled_rejects_invalid_bearer_token(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", AUTH_TOKEN_PROFILES)
    client = build_client(tmp_path)

    response = client.get("/runs", headers={"Authorization": "Bearer wrong-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid authentication credentials."


def test_role_permissions_constrain_read_write_and_approval_actions(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", AUTH_TOKEN_PROFILES)
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    repository.create_run("Seed readable run.")

    viewer_read = client.get("/runs", headers=VIEWER_HEADERS)
    viewer_write = client.post(
        "/runs",
        headers=VIEWER_HEADERS,
        json={"task": "Viewer should not create runs."},
    )
    approver_write = client.post(
        "/runs",
        headers=APPROVER_HEADERS,
        json={"task": "Approver should not create runs."},
    )
    operator_write = client.post(
        "/runs",
        headers=OPERATOR_HEADERS,
        json={"task": "Operator can create runs."},
    )

    body = operator_write.json()
    audit_event = next(
        event for event in repository.list_events(body["id"])
        if event.event_type == AgentEventType.AUDIT.value
    )
    run_detail = client.get(f"/runs/{body['id']}", headers=VIEWER_HEADERS).json()
    assert viewer_read.status_code == 200
    assert viewer_write.status_code == 403
    assert approver_write.status_code == 403
    assert operator_write.status_code == 201
    assert audit_event.payload["actor"]["id"] == "operator-1"
    assert audit_event.payload["actor"]["roles"] == ["operator"]
    assert audit_event.payload["run_id"] == body["id"]
    assert audit_event.payload["trace_id"] == body["trace_id"]
    assert run_detail["audit_events"][0]["action"] == "run.create"
    assert run_detail["audit_events"][0]["actor"]["id"] == "operator-1"
    assert run_detail["audit_events"][0]["target"] == {"run_id": body["id"]}


def test_app_can_select_sqlalchemy_run_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_BACKEND", "sqlalchemy")
    monkeypatch.setenv("AEAI_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'runs.db'}")
    app = create_app(artifact_root=tmp_path / "artifacts")
    client = TestClient(app)

    response = client.post("/runs", json={"task": "Analyze procurement spend."})

    assert app.state.run_repository.__class__.__name__ == "SQLAlchemyRunRepository"
    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_api_created_sqlalchemy_run_survives_app_recreation(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'persistent-runs.db'}"
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_BACKEND", "sqlalchemy")
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_CREATE_SCHEMA", "true")
    monkeypatch.setenv("AEAI_DATABASE_URL", database_url)

    first_client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    create_response = first_client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend.",
            "metadata": {"source": "restart-test"},
        },
    )
    run_id = create_response.json()["id"]

    second_client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    lookup_response = second_client.get(f"/runs/{run_id}")
    list_response = second_client.get("/runs")

    assert create_response.status_code == 201
    assert lookup_response.status_code == 200
    assert lookup_response.json()["id"] == run_id
    assert lookup_response.json()["task"] == "Analyze procurement spend."
    assert lookup_response.json()["metadata"] == {"source": "restart-test"}
    assert any(run["id"] == run_id for run in list_response.json())


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


def test_run_inspector_page_is_served(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/run-inspector/runs/run_example")

    assert response.status_code == 200
    assert "Run Inspector" in response.text
    assert "/run-inspector/run-inspector.js" in response.text
    assert 'id="actionText"' in response.text
    assert 'id="approvalHistory"' in response.text
    assert 'id="deploymentHistory"' in response.text


def test_run_inspector_script_exposes_detail_approval_and_retry_controls(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/run-inspector/run-inspector.js")

    assert response.status_code == 200
    assert 'data-node-action="approve"' in response.text
    assert 'data-node-action="deny"' in response.text
    assert 'data-node-action="retry"' in response.text
    assert 'data-deployment-action="approve"' in response.text
    assert 'data-deployment-action="deny"' in response.text
    assert 'data-job-action="retry"' in response.text
    assert 'data-job-action="dismiss"' in response.text
    assert "/graph-nodes/${encodedNodeId}/approval" in response.text
    assert "/graph-nodes/${encodedNodeId}/retry" in response.text
    assert "/deployments/${encodedJobId}/approval" in response.text
    assert "/workflow-jobs/${encodedJobId}/${action}" in response.text
    assert "/artifacts/${encodeURIComponent(artifact.id)}/lineage" in response.text
    assert "renderApprovalHistory" in response.text
    assert "renderDeploymentHistory" in response.text
    assert "mlflow_status" in response.text
    assert "Source artifacts" in response.text


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


def test_sqlalchemy_artifact_lineage_endpoint_survives_app_recreation(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'artifact-lineage.db'}"
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_BACKEND", "sqlalchemy")
    monkeypatch.setenv("AEAI_RUN_REPOSITORY_CREATE_SCHEMA", "true")
    monkeypatch.setenv("AEAI_DATABASE_URL", database_url)

    first_app = create_app(artifact_root=tmp_path / "artifacts")
    repository = first_app.state.run_repository
    run = repository.create_run("Analyze procurement spend.")
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://bucket/raw/procurement.csv",
        metadata={
            "storage_backend": "s3",
            "storage_key": "raw/procurement.csv",
            "content_type": "text/csv",
            "size_bytes": 1024,
        },
    )
    kpi = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.KPI_TABLE,
        uri="s3://bucket/analytics/kpis.json",
        metadata={"storage_backend": "s3", "storage_key": "analytics/kpis.json"},
        source_artifact_ids=[dataset.id],
        producer_node_id="analytics",
        content_type="application/json",
        size_bytes=512,
    )
    dashboard = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DASHBOARD,
        uri="s3://bucket/visualization/dashboard.html",
        metadata={"storage_backend": "s3", "storage_key": "visualization/dashboard.html"},
        source_artifact_ids=[kpi.id],
        producer_node_id="visualization",
        content_type="text/html",
        size_bytes=2048,
    )
    report = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri="s3://bucket/report/procurement.md",
        metadata={"storage_backend": "s3", "storage_key": "report/procurement.md"},
        source_artifact_ids=[dataset.id, dashboard.id],
        producer_node_id="report",
        content_type="text/markdown",
        size_bytes=1536,
    )

    second_client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    response = second_client.get(f"/runs/{run.id}/artifacts/{report.id}/lineage")
    body = response.json()
    upstream_ids = {artifact["id"] for artifact in body["upstream_artifacts"]}
    edge_pairs = {
        (edge["source_artifact_id"], edge["target_artifact_id"])
        for edge in body["edges"]
    }

    assert response.status_code == 200
    assert body["root_artifact"]["id"] == report.id
    assert body["root_artifact"]["storage_backend"] == "s3"
    assert body["root_artifact"]["storage_key"] == "report/procurement.md"
    assert body["root_artifact"]["content_type"] == "text/markdown"
    assert body["root_artifact"]["size_bytes"] == 1536
    assert {dataset.id, kpi.id, dashboard.id} <= upstream_ids
    assert (dataset.id, report.id) in edge_pairs
    assert (dashboard.id, report.id) in edge_pairs
    assert (kpi.id, dashboard.id) in edge_pairs


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


def test_execute_procurement_workflow_from_sqlite_warehouse_reference(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    db_path = tmp_path / "warehouse.db"
    write_procurement_sqlite_fixture(db_path)

    run = client.post(
        "/runs",
        json={"task": "Analyze this procurement dataset and create a dashboard report."},
    ).json()
    dataset_response = client.post(
        f"/runs/{run['id']}/datasets/reference",
        json={
            "uri": f"sqlite://{db_path}#procurement",
            "format": "sqlite",
            "metadata": {"source": "warehouse"},
        },
    )

    response = client.post(f"/runs/{run['id']}/execute/procurement")

    body = response.json()
    artifact_types = {artifact["type"] for artifact in body["artifacts"]}
    kpi_artifact = next(
        artifact for artifact in body["artifacts"] if artifact["type"] == "kpi_table"
    )
    assert dataset_response.status_code == 201
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert {"schema_profile", "quality_report", "kpi_table", "dashboard", "report"}.issubset(
        artifact_types
    )
    assert kpi_artifact["metadata"]["total_spend"] == 1410.0
    assert body["evaluations"][-1]["passed"] is True


def test_approve_waiting_graph_node_from_api(tmp_path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    app = create_app(repository=repository, artifact_root=artifact_root)
    client = TestClient(app)
    run = seed_waiting_data_profile_run(repository, artifact_root, tmp_path)

    response = client.post(
        f"/runs/{run.id}/graph-nodes/data_profile/approval",
        json={"approved": True, "comment": "Approved local profile step."},
    )

    body = response.json()
    artifact_types = {artifact["type"] for artifact in body["artifacts"]}
    event_types = [event.event_type for event in repository.list_events(run.id)]
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["completed_node_ids"] == ["data_profile"]
    assert body["waiting_for_approval_node_id"] is None
    assert {"schema_profile", "quality_report"}.issubset(artifact_types)
    assert AgentEventType.APPROVAL_DECISION in event_types


def test_deny_waiting_graph_node_from_api_marks_run_failed(tmp_path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    app = create_app(repository=repository, artifact_root=artifact_root)
    client = TestClient(app)
    run = seed_waiting_data_profile_run(repository, artifact_root, tmp_path)

    response = client.post(
        f"/runs/{run.id}/graph-nodes/data_profile/approval",
        json={"approved": False, "comment": "Do not run warehouse query."},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "failed"
    assert body["failed_node_ids"] == ["data_profile"]
    assert repository.get_checkpoint(run.id).state["approvals"] == {
        "data_profile": "denied"
    }


def test_approval_endpoint_rejects_node_that_is_not_waiting(tmp_path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    app = create_app(repository=repository, artifact_root=artifact_root)
    client = TestClient(app)
    run = seed_waiting_data_profile_run(repository, artifact_root, tmp_path)
    build_procurement_orchestrator(repository, artifact_root).approve_node(
        run.id,
        "data_profile",
        approved=True,
        comment="Approved outside the API.",
    )

    response = client.post(
        f"/runs/{run.id}/graph-nodes/data_profile/approval",
        json={"approved": True},
    )

    assert response.status_code == 400
    assert "not waiting for approval" in response.json()["detail"]


def test_approval_requires_approver_role_and_audits_actor(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", AUTH_TOKEN_PROFILES)
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    app = create_app(repository=repository, artifact_root=artifact_root)
    client = TestClient(app)
    run = seed_waiting_data_profile_run(repository, artifact_root, tmp_path)

    operator_response = client.post(
        f"/runs/{run.id}/graph-nodes/data_profile/approval",
        headers=OPERATOR_HEADERS,
        json={"approved": True, "comment": "Operator should not approve."},
    )
    reviewer_response = client.post(
        f"/runs/{run.id}/graph-nodes/data_profile/approval",
        headers=REVIEWER_HEADERS,
        json={"approved": True, "comment": "Reviewer can approve."},
    )
    audit_response = client.get(f"/runs/{run.id}/audit-events", headers=VIEWER_HEADERS)

    audit_events = [
        event for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.AUDIT.value
        and event.payload["action"] == "graph_node.approval"
    ]
    assert operator_response.status_code == 403
    assert reviewer_response.status_code == 200
    assert audit_response.status_code == 200
    assert audit_events[-1].payload["actor"]["id"] == "reviewer-1"
    assert audit_events[-1].payload["actor"]["roles"] == ["reviewer"]
    assert audit_events[-1].payload["run_id"] == run.id
    assert audit_events[-1].payload["trace_id"] == run.trace_id
    assert audit_events[-1].payload["details"]["approved"] is True
    assert audit_response.json()[-1]["action"] == "graph_node.approval"
    assert audit_response.json()[-1]["actor"]["id"] == "reviewer-1"
    assert audit_response.json()[-1]["trace_id"] == run.trace_id


def test_retry_failed_graph_node_from_api(tmp_path):
    repository = InMemoryRunRepository()
    artifact_root = tmp_path / "artifacts"
    app = create_app(repository=repository, artifact_root=artifact_root)
    client = TestClient(app)
    run = repository.create_run("Retry failed data profile.")
    graph = ExecutionGraph(
        run_id=run.id,
        nodes=[
            ExecutionNode(
                id="data_profile",
                agent="data_retrieval",
                task="Profile procurement dataset.",
                expected_artifacts=["schema_profile", "quality_report"],
            )
        ],
    )
    service = OrchestratorService(
        repository=repository,
        registry=build_default_registry(),
        agents={"data_retrieval": DataRetrievalAgent(repository, artifact_root)},
        retry_policy=RetryPolicy(max_attempts=1),
    )
    failed = service.execute_run(run.id, graph)
    dataset_path = tmp_path / "procurement_retry.csv"
    write_procurement_fixture(dataset_path)
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(dataset_path),
        metadata={"source": "test", "format": "csv"},
    )

    response = client.post(f"/runs/{run.id}/graph-nodes/data_profile/retry")

    body = response.json()
    artifact_types = {artifact["type"] for artifact in body["artifacts"]}
    assert failed.status.value == "failed"
    assert response.status_code == 200
    assert body["status"] == "completed"
    assert body["completed_node_ids"] == ["data_profile"]
    assert {"schema_profile", "quality_report"}.issubset(artifact_types)


def test_create_deployment_request_waits_for_approval_and_records_audit_event(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Deploy validated dashboard.")
    report = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.REPORT,
        uri=str(tmp_path / "report.md"),
        metadata={"source": "test", "format": "markdown"},
    )

    response = client.post(
        f"/runs/{run.id}/deployments",
        json={
            "artifact_ids": [report.id],
            "destination": "s3://approved-dashboards/procurement",
            "requested_by": "analytics-lead",
            "rationale": "Promote the validated procurement dashboard.",
        },
    )

    body = response.json()
    approval_events = [
        event
        for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.APPROVAL_REQUEST
    ]
    timeline_response = client.get(f"/runs/{run.id}/timeline")
    assert response.status_code == 202
    assert body["workflow_name"] == "deployment"
    assert body["status"] == WorkflowJobStatus.WAITING_FOR_APPROVAL
    assert body["payload"]["artifact_ids"] == [report.id]
    assert body["payload"]["deployment_status"] == "waiting_for_approval"
    assert repository.get_run(run.id).status == RunStatus.WAITING_FOR_APPROVAL
    assert approval_events[0].payload["decision"] == "pending"
    assert approval_events[0].payload["requested_by"] == "analytics-lead"
    assert any(
        item["workflow_job_id"] == body["id"]
        and item["status"] == WorkflowJobStatus.WAITING_FOR_APPROVAL
        for item in timeline_response.json()
    )


def test_approve_deployment_request_creates_deployment_artifact(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Deploy validated dashboard.")
    dashboard = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DASHBOARD,
        uri=str(tmp_path / "dashboard.html"),
        metadata={"source": "test", "format": "html"},
    )
    deployment_job = client.post(
        f"/runs/{run.id}/deployments",
        json={
            "artifact_ids": [dashboard.id],
            "destination": "azure://static-web-apps/procurement",
            "requested_by": "analytics-lead",
        },
    ).json()

    response = client.post(
        f"/runs/{run.id}/deployments/{deployment_job['id']}/approval",
        json={
            "approved": True,
            "approver": "release-manager",
            "rationale": "Evaluation passed and artifacts were reviewed.",
        },
    )

    body = response.json()
    deployment_artifacts = [
        artifact
        for artifact in repository.list_artifacts(run.id)
        if artifact.type == ArtifactType.DEPLOYMENT
    ]
    decision_events = [
        event
        for event in repository.list_events(run.id)
        if event.event_type == AgentEventType.APPROVAL_DECISION
    ]
    assert response.status_code == 200
    assert body["status"] == WorkflowJobStatus.COMPLETED
    assert body["payload"]["approval"]["decision"] == "approved"
    assert body["payload"]["approval"]["approver"] == "release-manager"
    assert body["payload"]["deployment_artifact_id"] == deployment_artifacts[0].id
    assert repository.get_run(run.id).status == RunStatus.COMPLETED
    assert deployment_artifacts[0].source_artifact_ids == [dashboard.id]
    assert deployment_artifacts[0].metadata["approved_by"] == "release-manager"
    assert deployment_artifacts[0].metadata["destination"] == "azure://static-web-apps/procurement"
    assert decision_events[0].payload["decision"] == "approved"
    assert decision_events[0].payload["approver"] == "release-manager"


def test_deny_deployment_request_fails_job_without_promotion_artifact(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Deploy validated dashboard.")
    dashboard = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DASHBOARD,
        uri=str(tmp_path / "dashboard.html"),
        metadata={"source": "test", "format": "html"},
    )
    deployment_job = client.post(
        f"/runs/{run.id}/deployments",
        json={
            "artifact_ids": [dashboard.id],
            "destination": "azure://static-web-apps/procurement",
            "requested_by": "analytics-lead",
        },
    ).json()

    response = client.post(
        f"/runs/{run.id}/deployments/{deployment_job['id']}/approval",
        json={
            "approved": False,
            "approver": "release-manager",
            "rationale": "Dashboard needs stakeholder review first.",
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == WorkflowJobStatus.FAILED
    assert body["error_summary"] == "Deployment approval denied."
    assert body["payload"]["approval"]["decision"] == "denied"
    assert repository.get_run(run.id).status == RunStatus.FAILED
    assert all(
        artifact.type != ArtifactType.DEPLOYMENT
        for artifact in repository.list_artifacts(run.id)
    )


def test_deployment_approval_rejects_invalid_state(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Deploy validated dashboard.")
    dashboard = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DASHBOARD,
        uri=str(tmp_path / "dashboard.html"),
        metadata={"source": "test", "format": "html"},
    )
    deployment_job = client.post(
        f"/runs/{run.id}/deployments",
        json={"artifact_ids": [dashboard.id], "destination": "local://preview"},
    ).json()
    client.post(
        f"/runs/{run.id}/deployments/{deployment_job['id']}/approval",
        json={"approved": True, "approver": "release-manager"},
    )

    response = client.post(
        f"/runs/{run.id}/deployments/{deployment_job['id']}/approval",
        json={"approved": True, "approver": "release-manager"},
    )

    assert response.status_code == 400
    assert "not waiting for approval" in response.json()["detail"]


def test_enqueue_procurement_workflow_from_api(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = client.post(
        "/runs",
        json={
            "task": "Analyze this procurement dataset and create a dashboard report.",
            "dataset_uri": str(dataset_path),
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/procurement/async")
    jobs_response = client.get(f"/runs/{run['id']}/workflow-jobs")

    assert response.status_code == 202
    job = response.json()
    assert job["run_id"] == run["id"]
    assert job["workflow_name"] == "procurement"
    assert job["status"] == "queued"
    assert job["attempt_count"] == 0
    assert job["max_attempts"] == 3
    assert jobs_response.status_code == 200
    assert jobs_response.json() == [job]


def test_enqueue_procurement_workflow_uses_configured_max_attempts(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_PROCUREMENT_WORKFLOW_MAX_ATTEMPTS", "5")
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = client.post(
        "/runs",
        json={
            "task": "Analyze this procurement dataset and create a dashboard report.",
            "dataset_uri": str(dataset_path),
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/procurement/async")

    assert response.status_code == 202
    assert response.json()["max_attempts"] == 5


def test_primary_procurement_execution_endpoint_enqueues_in_async_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_WORKFLOW_EXECUTION_MODE", "async")
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = client.post(
        "/runs",
        json={
            "task": "Analyze this procurement dataset and create a dashboard report.",
            "dataset_uri": str(dataset_path),
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute/procurement")

    body = response.json()
    audit_events = [
        event for event in repository.list_events(run["id"])
        if event.event_type == AgentEventType.AUDIT.value
        and event.payload["action"] == "workflow.enqueue_procurement"
    ]
    assert response.status_code == 202
    assert body["run_id"] == run["id"]
    assert body["workflow_name"] == "procurement"
    assert body["status"] == "queued"
    assert body["attempt_count"] == 0
    assert audit_events[0].payload["target"] == {
        "run_id": run["id"],
        "workflow_job_id": body["id"],
    }


def test_dead_letter_workflow_job_can_be_retried_and_dismissed_from_api(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    retry_run = repository.create_run("Retry dead-letter procurement job.")
    retry_job = repository.enqueue_workflow_job(retry_run.id, "procurement", max_attempts=1)
    retry_claim = repository.claim_next_workflow_job("worker-one")
    repository.fail_workflow_job(
        retry_claim.id,
        "Dataset artifact is missing.",
        retry=True,
    )
    dismiss_run = repository.create_run("Dismiss dead-letter procurement job.")
    dismiss_job = repository.enqueue_workflow_job(dismiss_run.id, "procurement", max_attempts=1)
    dismiss_claim = repository.claim_next_workflow_job("worker-one")
    repository.fail_workflow_job(
        dismiss_claim.id,
        "External dependency remained unavailable.",
        retry=True,
    )

    retry_response = client.post(
        f"/runs/{retry_run.id}/workflow-jobs/{retry_job.id}/retry",
        json={"reason": "Dataset was attached after failure."},
    )
    dismiss_response = client.post(
        f"/runs/{dismiss_run.id}/workflow-jobs/{dismiss_job.id}/dismiss",
        json={"reason": "Superseded by a new run."},
    )

    retry_body = retry_response.json()
    dismiss_body = dismiss_response.json()
    audit_actions = [
        event.payload["action"]
        for event in repository.list_events(retry_run.id)
        + repository.list_events(dismiss_run.id)
        if event.event_type == AgentEventType.AUDIT.value
    ]
    assert retry_response.status_code == 200
    assert retry_body["status"] == "queued"
    assert retry_body["max_attempts"] == 2
    assert retry_body["payload"]["manual_retry_count"] == 1
    assert retry_body["payload"]["last_manual_retry_reason"] == (
        "Dataset was attached after failure."
    )
    assert repository.get_run(retry_run.id).status == RunStatus.PENDING
    assert dismiss_response.status_code == 200
    assert dismiss_body["status"] == "dismissed"
    assert dismiss_body["payload"]["dismissal_reason"] == "Superseded by a new run."
    assert {
        "workflow.retry_dead_letter",
        "workflow.dismiss_dead_letter",
    }.issubset(set(audit_actions))


def test_dead_letter_controls_reject_non_dead_letter_jobs(tmp_path):
    repository = InMemoryRunRepository()
    app = create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    client = TestClient(app)
    run = repository.create_run("Reject invalid manual retry.")
    job = repository.enqueue_workflow_job(run.id, "procurement")

    response = client.post(
        f"/runs/{run.id}/workflow-jobs/{job.id}/retry",
        json={"reason": "This job is still queued."},
    )

    assert response.status_code == 400
    assert "must be dead_letter" in response.json()["detail"]


def test_run_inspection_endpoints_expose_graph_events_and_timeline(tmp_path):
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
    created_at = utc_now()
    repository.add_graph_node(
        GraphNodeRecord(
            id="data_profile",
            run_id=run.id,
            agent_type="data_retrieval",
            status=GraphNodeStatus.COMPLETED,
            depends_on=[],
            required_tools=["local_file_read"],
            expected_artifacts=["schema_profile", "quality_report"],
            retry_count=0,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    repository.add_event(
        AgentEventRecord(
            id="event_data_profile",
            run_id=run.id,
            node_id="data_profile",
            event_type=AgentEventType.TOOL_CALL.value,
            payload={"message": "Profiled dataset.", "artifact_id": dataset.id},
            created_at=utc_now(),
        )
    )
    repository.add_evaluation(
        EvaluationResultRecord(
            id="evaluation_test",
            run_id=run.id,
            target_artifact_id=dataset.id,
            score=1.0,
            passed=True,
            checks=[{"name": "dataset_available", "passed": True, "score": 1.0}],
        )
    )
    job = repository.enqueue_workflow_job(run.id, "procurement")
    claimed = repository.claim_next_workflow_job("worker-test", "procurement")
    repository.complete_workflow_job(claimed.id)

    graph_response = client.get(f"/runs/{run.id}/graph-nodes")
    events_response = client.get(f"/runs/{run.id}/events")
    timeline_response = client.get(f"/runs/{run.id}/timeline")

    assert graph_response.status_code == 200
    assert graph_response.json()[0]["id"] == "data_profile"
    assert graph_response.json()[0]["status"] == "completed"
    assert graph_response.json()[0]["required_tools"] == ["local_file_read"]
    assert events_response.status_code == 200
    event_types = {event["event_type"] for event in events_response.json()}
    assert {"tool_call", "evaluation"}.issubset(event_types)
    assert timeline_response.status_code == 200
    timeline = timeline_response.json()
    kinds = {item["kind"] for item in timeline}
    assert {
        "run",
        "workflow_job",
        "graph_node",
        "agent_event",
        "artifact",
        "evaluation",
    }.issubset(kinds)
    assert any(item["workflow_job_id"] == job.id for item in timeline)
    assert any(item["artifact_id"] == dataset.id for item in timeline)


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


def test_upload_dataset_writes_payload_through_artifact_store(tmp_path):
    client = build_client(tmp_path)
    run = client.post("/runs", json={"task": "Analyze procurement spend."}).json()

    response = client.post(
        f"/runs/{run['id']}/datasets/upload",
        files={
            "file": (
                "procurement.csv",
                b"supplier,spend_amount\nAcme,100\n",
                "text/csv",
            )
        },
    )

    assert response.status_code == 201
    artifact = response.json()
    assert artifact["type"] == "dataset"
    assert artifact["metadata"]["storage_backend"] == "local"
    assert artifact["metadata"]["storage_key"].endswith("/datasets/" + artifact["id"] + ".csv")
    assert Path(artifact["uri"]).read_text(encoding="utf-8") == "supplier,spend_amount\nAcme,100\n"

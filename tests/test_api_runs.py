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
    assert "/graph-nodes/${encodedNodeId}/approval" in response.text
    assert "/graph-nodes/${encodedNodeId}/retry" in response.text
    assert "/deployments/${encodedJobId}/approval" in response.text
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

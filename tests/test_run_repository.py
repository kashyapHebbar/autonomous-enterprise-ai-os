from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord, GraphNodeRecord
from aeai_os.runs.repository import (
    InMemoryRunRepository,
    RunNotFoundError,
    WorkflowJobOwnershipError,
    utc_now,
)
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.schemas.enums import (
    AgentEventType,
    ArtifactType,
    GraphNodeStatus,
    RunStatus,
    WorkflowJobStatus,
)


@pytest.fixture(params=["memory", "sqlalchemy"])
def repository(request):
    if request.param == "memory":
        return InMemoryRunRepository()

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return SQLAlchemyRunRepository.from_engine(engine, create_schema=True)


def test_repository_creates_pending_run_and_attaches_dataset(repository):
    run = repository.create_run("Analyze procurement data.")
    artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://bucket/procurement.csv",
        metadata={"source": "reference"},
    )

    updated = repository.get_run(run.id)
    assert updated.status == RunStatus.PENDING
    assert updated.dataset_artifact_id == artifact.id
    assert repository.list_runs() == [updated]
    assert repository.list_artifacts(run.id) == [artifact]


def test_repository_rejects_short_task(repository):
    with pytest.raises(ValueError):
        repository.create_run("  ")


def test_repository_raises_for_missing_run(repository):
    with pytest.raises(RunNotFoundError):
        repository.get_run("run_missing")


def test_repository_updates_run_status(repository):
    run = repository.create_run("Analyze procurement data.")

    updated = repository.update_status(
        run_id=run.id,
        status=RunStatus.FAILED,
        error_summary="Dataset quality gate failed.",
    )

    assert updated.status == RunStatus.FAILED
    assert updated.error_summary == "Dataset quality gate failed."
    assert updated.updated_at >= run.updated_at
    assert repository.get_run(run.id) == updated


def test_repository_persists_graph_events_evaluations_and_checkpoints(repository):
    run = repository.create_run("Analyze procurement data.")
    created_at = utc_now()
    node = GraphNodeRecord(
        id="profile",
        run_id=run.id,
        agent_type="data_retrieval",
        status=GraphNodeStatus.PENDING,
        depends_on=[],
        required_tools=["local_file_read"],
        expected_artifacts=["schema_profile"],
        retry_count=0,
        created_at=created_at,
        updated_at=created_at,
    )

    repository.add_graph_node(node)
    completed_node = replace(
        node,
        status=GraphNodeStatus.COMPLETED,
        retry_count=1,
        updated_at=utc_now(),
    )
    repository.upsert_graph_node(completed_node)
    event = AgentEventRecord(
        id="event_profile_log",
        run_id=run.id,
        node_id="profile",
        event_type=AgentEventType.LOG.value,
        payload={"message": "profile complete"},
        created_at=utc_now(),
    )
    evaluation = EvaluationResultRecord(
        id="evaluation_profile",
        run_id=run.id,
        target_artifact_id=None,
        score=0.95,
        passed=True,
        checks=[{"name": "schema_profile", "passed": True, "score": 1.0}],
    )

    repository.add_event(event)
    saved_evaluation = repository.add_evaluation(evaluation)
    first_checkpoint = repository.save_checkpoint(
        run.id,
        {"run_id": run.id, "completed_node_ids": ["profile"]},
    )
    second_checkpoint = repository.save_checkpoint(
        run.id,
        {"run_id": run.id, "completed_node_ids": ["profile"], "status": "done"},
    )
    second_checkpoint.state["status"] = "mutated"

    assert repository.get_graph_node(run.id, "profile") == completed_node
    assert repository.list_graph_nodes(run.id) == [completed_node]
    assert repository.list_events(run.id)[0] == event
    assert any(
        logged_event.event_type == AgentEventType.EVALUATION.value
        for logged_event in repository.list_events(run.id)
    )
    assert saved_evaluation.created_at is not None
    assert repository.get_evaluation(run.id, "evaluation_profile") == saved_evaluation
    assert repository.list_evaluations(run.id) == [saved_evaluation]
    assert first_checkpoint.version == 1
    assert second_checkpoint.version == 2
    assert repository.get_checkpoint(run.id).state["status"] == "done"


def test_repository_allows_reused_graph_node_ids_across_runs(repository):
    first_run = repository.create_run("Analyze first procurement dataset.")
    second_run = repository.create_run("Analyze second procurement dataset.")
    created_at = utc_now()

    for run in [first_run, second_run]:
        repository.add_graph_node(
            GraphNodeRecord(
                id="profile",
                run_id=run.id,
                agent_type="data_retrieval",
                status=GraphNodeStatus.PENDING,
                depends_on=[],
                required_tools=[],
                expected_artifacts=[],
                retry_count=0,
                created_at=created_at,
                updated_at=created_at,
            )
        )

    assert len(repository.list_graph_nodes(first_run.id)) == 1
    assert len(repository.list_graph_nodes(second_run.id)) == 1
    assert repository.get_graph_node(first_run.id, "profile").run_id == first_run.id
    assert repository.get_graph_node(second_run.id, "profile").run_id == second_run.id


def test_repository_persists_and_claims_workflow_jobs(repository):
    run = repository.create_run("Analyze procurement data.")

    job = repository.enqueue_workflow_job(
        run_id=run.id,
        workflow_name="procurement",
        payload={"priority": "normal"},
        max_attempts=2,
    )
    claimed = repository.claim_next_workflow_job(
        worker_id="worker-test",
        workflow_name="procurement",
    )
    requeued = repository.fail_workflow_job(
        claimed.id,
        "Temporary warehouse timeout.",
        retry=True,
    )
    claimed_again = repository.claim_next_workflow_job(
        worker_id="worker-test",
        workflow_name="procurement",
    )
    completed = repository.complete_workflow_job(claimed_again.id, worker_id="worker-test")

    assert job.status == WorkflowJobStatus.QUEUED
    assert job.payload == {"priority": "normal"}
    assert claimed.id == job.id
    assert claimed.status == WorkflowJobStatus.RUNNING
    assert claimed.attempt_count == 1
    assert claimed.worker_id == "worker-test"
    assert claimed.heartbeat_at is not None
    assert requeued.status == WorkflowJobStatus.QUEUED
    assert requeued.error_summary == "Temporary warehouse timeout."
    assert claimed_again.attempt_count == 2
    assert completed.status == WorkflowJobStatus.COMPLETED
    assert completed.finished_at is not None
    assert repository.get_workflow_job(job.id) == completed
    assert repository.list_workflow_jobs(run_id=run.id) == [completed]
    assert repository.list_workflow_jobs(status=WorkflowJobStatus.COMPLETED) == [completed]
    assert repository.claim_next_workflow_job(worker_id="worker-test") is None


def test_repository_marks_workflow_job_failed_after_attempts_are_exhausted(repository):
    run = repository.create_run("Analyze procurement data.")
    job = repository.enqueue_workflow_job(
        run_id=run.id,
        workflow_name="procurement",
        max_attempts=1,
    )
    claimed = repository.claim_next_workflow_job(worker_id="worker-test")

    failed = repository.fail_workflow_job(
        claimed.id,
        "Dataset artifact is missing.",
        retry=True,
    )

    assert failed.id == job.id
    assert failed.status == WorkflowJobStatus.DEAD_LETTER
    assert failed.error_summary == "Dataset artifact is missing."
    assert failed.finished_at is not None


def test_repository_rejects_workflow_job_updates_from_non_owner(repository):
    run = repository.create_run("Analyze procurement data.")
    job = repository.enqueue_workflow_job(run.id, "procurement")
    claimed = repository.claim_next_workflow_job("worker-owner")

    with pytest.raises(WorkflowJobOwnershipError):
        repository.complete_workflow_job(job.id, worker_id="worker-other")

    with pytest.raises(WorkflowJobOwnershipError):
        repository.fail_workflow_job(
            job.id,
            "Other worker should not fail this job.",
            worker_id="worker-other",
        )

    completed = repository.complete_workflow_job(claimed.id, worker_id="worker-owner")

    assert completed.status == WorkflowJobStatus.COMPLETED


def test_repository_heartbeats_and_recovers_timed_out_workflow_jobs(repository):
    run = repository.create_run("Analyze procurement data.")
    job = repository.enqueue_workflow_job(run.id, "procurement", max_attempts=2)
    claimed = repository.claim_next_workflow_job("worker-one")

    heartbeat = repository.heartbeat_workflow_job(claimed.id, worker_id="worker-one")
    recovered = repository.recover_timed_out_workflow_jobs(
        timeout_seconds=300,
        now=heartbeat.heartbeat_at + timedelta(seconds=301),
    )
    reclaimed = repository.claim_next_workflow_job("worker-two")

    assert claimed.id == job.id
    assert heartbeat.heartbeat_at >= claimed.heartbeat_at
    assert recovered[0].id == job.id
    assert recovered[0].status == WorkflowJobStatus.QUEUED
    assert recovered[0].worker_id is None
    assert "heartbeat timed out" in recovered[0].error_summary
    assert reclaimed.id == job.id
    assert reclaimed.worker_id == "worker-two"
    assert reclaimed.attempt_count == 2


def test_repository_dead_letters_timed_out_job_after_attempts_exhausted(repository):
    run = repository.create_run("Analyze procurement data.")
    job = repository.enqueue_workflow_job(run.id, "procurement", max_attempts=1)
    claimed = repository.claim_next_workflow_job("worker-one")

    recovered = repository.recover_timed_out_workflow_jobs(
        timeout_seconds=300,
        now=claimed.heartbeat_at + timedelta(seconds=301),
    )

    assert recovered[0].id == job.id
    assert recovered[0].status == WorkflowJobStatus.DEAD_LETTER
    assert recovered[0].worker_id == "worker-one"
    assert recovered[0].finished_at is not None
    assert repository.claim_next_workflow_job("worker-two") is None

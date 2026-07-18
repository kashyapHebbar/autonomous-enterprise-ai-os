from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType, RunStatus, WorkflowJobStatus
from aeai_os.workflows.worker import WorkflowWorker, enqueue_procurement_workflow


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


def test_workflow_worker_processes_queued_procurement_job(tmp_path):
    repository = InMemoryRunRepository()
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = repository.create_run(
        "Analyze this procurement dataset and create a dashboard report."
    )
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(dataset_path),
        metadata={"source": "test", "format": "csv"},
    )
    job = enqueue_procurement_workflow(repository, run.id)

    processed = WorkflowWorker(
        repository=repository,
        artifact_root=tmp_path / "artifacts",
        worker_id="worker-test",
    ).process_next_job()

    assert processed.id == job.id
    assert processed.status == WorkflowJobStatus.COMPLETED
    assert processed.worker_id == "worker-test"
    assert processed.attempt_count == 1
    assert processed.finished_at is not None
    assert repository.get_run(run.id).status == RunStatus.COMPLETED
    assert repository.claim_next_workflow_job(worker_id="worker-test") is None


def test_workflow_worker_retries_then_records_final_failure(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run(
        "Analyze this procurement dataset and create a dashboard report."
    )
    job = enqueue_procurement_workflow(repository, run.id, max_attempts=2)
    worker = WorkflowWorker(
        repository=repository,
        artifact_root=tmp_path / "artifacts",
        worker_id="worker-test",
    )

    requeued = worker.process_next_job()
    failed = worker.process_next_job()

    assert requeued.id == job.id
    assert requeued.status == WorkflowJobStatus.QUEUED
    assert requeued.attempt_count == 1
    assert "dataset artifact must be attached" in requeued.error_summary
    assert failed.status == WorkflowJobStatus.DEAD_LETTER
    assert failed.attempt_count == 2
    assert failed.finished_at is not None
    assert repository.get_run(run.id).status == RunStatus.FAILED


def test_workflow_worker_returns_none_when_no_procurement_job_is_pending(tmp_path):
    repository = InMemoryRunRepository()
    worker = WorkflowWorker(
        repository=repository,
        artifact_root=tmp_path / "artifacts",
        worker_id="worker-idle",
    )

    assert worker.process_next_job() is None

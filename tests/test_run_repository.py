import pytest

from aeai_os.runs.repository import InMemoryRunRepository, RunNotFoundError
from aeai_os.schemas.enums import ArtifactType, RunStatus


def test_repository_creates_pending_run_and_attaches_dataset():
    repository = InMemoryRunRepository()

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
    assert repository.list_artifacts(run.id) == [artifact]


def test_repository_rejects_short_task():
    repository = InMemoryRunRepository()

    with pytest.raises(ValueError):
        repository.create_run("  ")


def test_repository_raises_for_missing_run():
    repository = InMemoryRunRepository()

    with pytest.raises(RunNotFoundError):
        repository.get_run("run_missing")

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

import aeai_os.storage.artifacts as artifact_storage
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType, RunStatus
from aeai_os.settings import AppSettings
from aeai_os.storage import (
    ArtifactStorageConfigurationError,
    ArtifactStorageError,
    LocalArtifactStore,
    S3ArtifactStore,
    build_artifact_store,
)
from aeai_os.workflows import execute_procurement_workflow


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, **kwargs) -> None:
        body = kwargs["Body"]
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            **kwargs,
            "Body": bytes(body),
        }

    def get_object(self, Bucket: str, Key: str) -> dict:
        return {"Body": BytesIO(self.objects[(Bucket, Key)]["Body"])}


class FakeHttpHeaders:
    def get_content_type(self) -> str:
        return "text/csv"


class FakeHttpResponse:
    headers = FakeHttpHeaders()

    def __init__(self, uri: str, payload: bytes) -> None:
        self.uri = uri
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def geturl(self) -> str:
        return self.uri

    def read(self, _limit: int) -> bytes:
        return self.payload


class FakeHttpOpener:
    def __init__(self, uri: str, payload: bytes) -> None:
        self.uri = uri
        self.payload = payload
        self.calls = 0

    def open(self, _request, timeout: int):
        assert timeout == artifact_storage.PUBLIC_DATASET_TIMEOUT_SECONDS
        self.calls += 1
        return FakeHttpResponse(self.uri, self.payload)


def write_procurement_fixture(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-05,100,IT",
                "Acme,Software,2026-01-06,100,IT",
                "Zenith,Hardware,2026-02-01,200,Operations",
                "Acme,Cloud,2026-02-10,1000,IT",
            ]
        ),
        encoding="utf-8",
    )


def test_local_artifact_store_writes_reads_and_reports_metadata(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")

    stored = store.write_json(
        run_id="run_123",
        node_id="data_profile",
        filename="schema.json",
        payload={"columns": ["supplier"]},
    )

    assert stored.uri.endswith("run_123/data_profile/schema.json")
    assert store.read_json(stored.uri) == {"columns": ["supplier"]}
    assert store.local_path(stored.uri).exists()
    assert stored.metadata["storage_backend"] == "local"
    assert stored.metadata["storage_key"] == "run_123/data_profile/schema.json"
    assert stored.metadata["content_type"] == "application/json"
    assert stored.metadata["credential_profile_id"] == "local-filesystem"


def test_local_artifact_store_downloads_public_https_csv_once(tmp_path, monkeypatch):
    uri = "https://data.example.com/procurement.csv"
    payload = b"supplier,spend_amount\nAcme,100\n"
    opener = FakeHttpOpener(uri, payload)
    monkeypatch.setattr(
        artifact_storage.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(artifact_storage, "build_opener", lambda *_handlers: opener)
    store = LocalArtifactStore(tmp_path / "artifacts")

    first_path = store.local_path(uri)
    second_path = store.local_path(uri)

    assert first_path == second_path
    assert first_path.read_bytes() == payload
    assert opener.calls == 1


def test_local_artifact_store_rejects_non_public_dataset_hosts(tmp_path, monkeypatch):
    monkeypatch.setattr(
        artifact_storage.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStorageError, match="non-public network address"):
        store.local_path("https://localhost/procurement.csv")


@pytest.mark.parametrize(
    ("uri", "message"),
    [
        ("http://data.example.com/procurement.csv", "must use HTTPS"),
        ("https://data.example.com/procurement.json", "must reference a .csv file"),
    ],
)
def test_local_artifact_store_rejects_unsafe_public_dataset_urls(
    tmp_path, uri, message
):
    store = LocalArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactStorageError, match=message):
        store.local_path(uri)


def test_s3_artifact_store_uses_stable_s3_uris_and_mock_client(tmp_path):
    client = FakeS3Client()
    store = S3ArtifactStore(
        bucket="aeai-artifacts",
        prefix="prod/runs",
        endpoint_url="http://minio:9000",
        local_cache_root=tmp_path / "cache",
        client=client,
    )

    stored = store.write_text(
        run_id="run 123",
        node_id="report/final",
        filename="report.md",
        payload="# Report",
        content_type="text/markdown",
        metadata={"producer": "report_agent"},
    )

    assert stored.uri == "s3://aeai-artifacts/prod/runs/run_123/report_final/report.md"
    assert stored.metadata["storage_backend"] == "s3"
    assert stored.metadata["bucket"] == "aeai-artifacts"
    assert stored.metadata["credential_profile_id"] == "artifact-s3-default"
    assert stored.metadata["storage_key"] == "prod/runs/run_123/report_final/report.md"
    assert store.read_text(stored.uri) == "# Report"
    assert store.local_path(stored.uri).read_text(encoding="utf-8") == "# Report"
    request = client.objects[("aeai-artifacts", "prod/runs/run_123/report_final/report.md")]
    assert request["ContentType"] == "text/markdown"
    assert request["Metadata"]["producer"] == "report_agent"


def test_s3_artifact_store_requires_bucket():
    with pytest.raises(ArtifactStorageConfigurationError, match="AEAI_ARTIFACT_S3_BUCKET"):
        S3ArtifactStore(bucket="", client=FakeS3Client())


def test_build_artifact_store_preserves_local_default(tmp_path):
    settings = AppSettings(artifact_root=str(tmp_path / "ignored"))

    store = build_artifact_store(settings, artifact_root=tmp_path / "override")

    stored = store.write_text("run_1", "node", "artifact.txt", "hello")
    assert stored.uri.startswith(str(tmp_path / "override"))


def test_procurement_workflow_writes_generated_artifacts_to_s3_store(tmp_path):
    repository = InMemoryRunRepository()
    dataset_path = tmp_path / "procurement.csv"
    write_procurement_fixture(dataset_path)
    run = repository.create_run("Analyze this procurement dataset and create a dashboard report.")
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(dataset_path),
        metadata={"source": "test", "format": "csv"},
    )
    store = S3ArtifactStore(
        bucket="aeai-artifacts",
        prefix="workflow",
        local_cache_root=tmp_path / "cache",
        client=FakeS3Client(),
    )

    result = execute_procurement_workflow(
        repository=repository,
        artifact_root=tmp_path / "artifacts",
        run_id=run.id,
        artifact_store=store,
    )

    assert result.status == RunStatus.COMPLETED
    generated_artifacts = [
        artifact for artifact in repository.list_artifacts(run.id) if artifact.id != dataset.id
    ]
    assert generated_artifacts
    assert all(
        artifact.uri.startswith("s3://aeai-artifacts/workflow/")
        for artifact in generated_artifacts
    )
    assert all(artifact.metadata["storage_backend"] == "s3" for artifact in generated_artifacts)
    assert all(
        artifact.metadata["credential_profile_id"] == "artifact-s3-default"
        for artifact in generated_artifacts
    )
    assert all(artifact.storage_backend == "s3" for artifact in generated_artifacts)
    assert all(artifact.storage_key for artifact in generated_artifacts)
    assert all(artifact.content_type for artifact in generated_artifacts)
    assert all(artifact.size_bytes and artifact.size_bytes > 0 for artifact in generated_artifacts)
    reports = [artifact for artifact in generated_artifacts if artifact.type == ArtifactType.REPORT]
    assert "Procurement Analysis Report" in store.read_text(reports[-1].uri)

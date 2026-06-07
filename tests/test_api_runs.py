from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository


def build_client(tmp_path):
    app = create_app(repository=InMemoryRunRepository(), artifact_root=tmp_path / "artifacts")
    return TestClient(app)


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


def test_upload_dataset_rejects_unsupported_file_type(tmp_path):
    client = build_client(tmp_path)
    run = client.post("/runs", json={"task": "Analyze procurement spend."}).json()

    response = client.post(
        f"/runs/{run['id']}/datasets/upload",
        files={"file": ("malware.exe", b"not a dataset", "application/octet-stream")},
    )

    assert response.status_code == 400

"""Regression coverage for the existing APIs used by the grouped React explorer.

No backend API rewrite is needed: grouped outputs and searchable event presentation
are client-side views over run-scoped, authorized metadata/content endpoints.
"""

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository


def test_existing_backend_exposes_groupable_artifacts_and_event_metadata(tmp_path):
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    created = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend, anomalies and supplier risk",
            "dataset_uri": "examples/procurement_demo.csv",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    result = client.post(f"/runs/{run_id}/execute")
    assert result.status_code == 200
    assert result.json()["status"] == "completed"

    artifacts_response = client.get(f"/runs/{run_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    kinds = {a["type"] for a in artifacts}
    assert {"report", "dashboard", "chart", "kpi_table", "dataset", "evaluation"} <= kinds
    assert all(a.get("id") and a.get("run_id") == run_id for a in artifacts)
    assert any(a.get("producer_node_id") == "visualization" for a in artifacts)
    assert any(a.get("producer_node_id") == "report" for a in artifacts)

    reports = [a for a in artifacts if a["type"] == "report"]
    assert {a["metadata"]["format"] for a in reports} == {"html", "markdown"}
    executive = next(a for a in reports if a["metadata"]["format"] == "html")
    inline = client.get(f"/runs/{run_id}/artifacts/{executive['id']}/content")
    download = client.get(f"/runs/{run_id}/artifacts/{executive['id']}/content?download=true")
    assert inline.status_code == 200
    assert inline.headers["content-type"].startswith("text/html")
    assert download.status_code == 200
    assert "attachment;" in download.headers["content-disposition"]
    assert inline.content == download.content

    events_response = client.get(f"/runs/{run_id}/events")
    assert events_response.status_code == 200
    events = events_response.json()
    assert events
    assert all("event_type" in e and "node_id" in e and "created_at" in e for e in events)
    assert any(e["node_id"] == "report" for e in events)


def test_dataset_reference_cannot_be_downloaded_as_an_output(tmp_path):
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    created = client.post(
        "/runs",
        json={"task": "Analyze procurement", "dataset_uri": "examples/procurement_demo.csv"},
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    dataset = next(a for a in created.json()["artifacts"] if a["type"] == "dataset")
    response = client.get(f"/runs/{run_id}/artifacts/{dataset['id']}/content?download=true")
    assert response.status_code == 403

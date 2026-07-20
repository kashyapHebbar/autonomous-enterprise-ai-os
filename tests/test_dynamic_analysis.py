from __future__ import annotations

import csv

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository


def _write_sales_fixture(path):
    rows = [
        {
            "order_id": "A-1",
            "region": "North",
            "revenue": "1200",
            "units": "12",
            "order_date": "2026-01-05",
        },
        {
            "order_id": "A-2",
            "region": "South",
            "revenue": "900",
            "units": "9",
            "order_date": "2026-01-12",
        },
        {
            "order_id": "A-3",
            "region": "North",
            "revenue": "1400",
            "units": "13",
            "order_date": "2026-02-03",
        },
        {
            "order_id": "A-4",
            "region": "West",
            "revenue": "5200",
            "units": "18",
            "order_date": "2026-02-20",
        },
        {
            "order_id": "A-5",
            "region": "South",
            "revenue": "1100",
            "units": "11",
            "order_date": "2026-03-02",
        },
        {
            "order_id": "A-6",
            "region": "North",
            "revenue": "1600",
            "units": "15",
            "order_date": "2026-03-18",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_dynamic_execution_routes_non_procurement_data_to_generic_recipe(tmp_path):
    dataset = tmp_path / "sales.csv"
    _write_sales_fixture(dataset)
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze regional sales trends, unusual values, and create a dashboard.",
            "dataset_uri": str(dataset),
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute")

    assert response.status_code == 200
    body = response.json()
    events = client.get(f"/runs/{run['id']}/events").json()
    errors = [item["payload"] for item in events if item["event_type"] == "error"]
    assert body["status"] == "completed", errors
    kpi = next(item for item in body["artifacts"] if item["type"] == "kpi_table")
    dashboard = next(item for item in body["artifacts"] if item["type"] == "dashboard")
    report = next(item for item in body["artifacts"] if item["type"] == "report")
    assert kpi["metadata"]["analysis_type"] == "generic"
    assert kpi["metadata"]["row_count"] == 6
    assert dashboard["metadata"]["title"] == "Dataset Intelligence Dashboard"
    assert report["metadata"]["title"] == "Exploratory Dataset Analysis Report"
    assert body["evaluations"][0]["passed"] is True


def test_dynamic_execution_preserves_procurement_recipe(tmp_path):
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    run = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend and supplier risk.",
            "dataset_uri": "examples/procurement_demo.csv",
        },
    ).json()

    response = client.post(f"/runs/{run['id']}/execute")

    kpi = next(item for item in response.json()["artifacts"] if item["type"] == "kpi_table")
    assert response.status_code == 200
    assert kpi["metadata"]["analysis_type"] == "procurement"
    assert kpi["metadata"]["total_spend"] == 165962.5

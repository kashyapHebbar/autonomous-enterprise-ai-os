from __future__ import annotations

import sqlite3
import sys
from io import BytesIO
from types import SimpleNamespace

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app


def test_local_connector_browses_previews_and_publishes_workflow_source(tmp_path):
    dataset_root = tmp_path / "datasets"
    dataset_root.mkdir()
    dataset = dataset_root / "regional_sales.csv"
    dataset.write_text(
        "order_id,region,revenue,order_date\n"
        "A-1,North,1200,2026-01-05\n"
        "A-2,South,900,2026-01-12\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    installation = client.post(
        "/connectors/installations",
        json={
            "connector_id": "local-file",
            "name": "Analytics files",
            "configuration": {"dataset_root": str(dataset_root)},
        },
    ).json()

    probe = client.post(
        f"/connectors/installations/{installation['id']}/test?probe=true"
    )
    browse = client.get(f"/connectors/installations/{installation['id']}/browse")
    preview = client.post(
        f"/connectors/installations/{installation['id']}/preview",
        json={"asset_id": "regional_sales.csv", "limit": 1},
    )
    source = client.post(
        f"/connectors/installations/{installation['id']}/sources",
        json={
            "asset_id": "regional_sales.csv",
            "data_source_id": "regional-sales",
            "name": "Regional Sales",
            "owner": "analytics-platform",
        },
    )

    assert probe.status_code == 200
    assert probe.json()["status"] == "ok"
    assert browse.status_code == 200
    assert browse.json()["assets"][0]["id"] == "regional_sales.csv"
    assert browse.json()["assets"][0]["can_select"] is True
    assert preview.status_code == 200
    assert preview.json()["rows"] == [
        {
            "order_id": "A-1",
            "region": "North",
            "revenue": "1200",
            "order_date": "2026-01-05",
        }
    ]
    assert preview.json()["truncated"] is True
    assert source.status_code == 201
    assert source.json()["metadata"]["installation_id"] == installation["id"]

    run = client.post(
        "/runs",
        json={"task": "Analyze regional sales.", "data_source_id": "regional-sales"},
    )
    execution = client.post(f"/runs/{run.json()['id']}/execute")

    assert run.status_code == 201
    assert execution.status_code == 200
    assert execution.json()["status"] == "completed"


def test_local_connector_rejects_paths_outside_configured_root(tmp_path):
    root = tmp_path / "datasets"
    root.mkdir()
    (tmp_path / "private.csv").write_text("secret\nvalue\n", encoding="utf-8")
    client = TestClient(create_app())
    installation = client.post(
        "/connectors/installations",
        json={
            "connector_id": "local-file",
            "name": "Safe files",
            "configuration": {"dataset_root": str(root)},
        },
    ).json()

    response = client.post(
        f"/connectors/installations/{installation['id']}/preview",
        json={"asset_id": "../private.csv"},
    )

    assert response.status_code == 422
    assert "escapes the configured root" in response.json()["detail"]
    assert "value" not in response.text


def test_sqlite_connector_browses_previews_publishes_and_executes(tmp_path):
    database = tmp_path / "warehouse.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE sales (order_id TEXT, region TEXT, revenue REAL, order_date TEXT)"
        )
        connection.executemany(
            "INSERT INTO sales VALUES (?, ?, ?, ?)",
            [
                ("A-1", "North", 1200, "2026-01-05"),
                ("A-2", "South", 900, "2026-01-12"),
                ("A-3", "West", 2200, "2026-02-02"),
                ("A-4", "North", 1800, "2026-02-10"),
            ],
        )
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))
    installation = client.post(
        "/connectors/installations",
        json={
            "connector_id": "sqlite-local",
            "name": "Sales warehouse",
            "configuration": {"database_path": str(database)},
        },
    ).json()

    probe = client.post(
        f"/connectors/installations/{installation['id']}/test?probe=true"
    )
    browse = client.get(f"/connectors/installations/{installation['id']}/browse")
    preview = client.post(
        f"/connectors/installations/{installation['id']}/preview",
        json={"asset_id": "sales", "limit": 2},
    )
    source = client.post(
        f"/connectors/installations/{installation['id']}/sources",
        json={
            "asset_id": "sales",
            "data_source_id": "warehouse-sales",
            "name": "Warehouse Sales",
            "owner": "analytics-platform",
        },
    )

    assert probe.json()["status"] == "ok"
    assert browse.json()["assets"][0]["name"] == "sales"
    assert [column["name"] for column in preview.json()["columns"]] == [
        "order_id",
        "region",
        "revenue",
        "order_date",
    ]
    assert len(preview.json()["rows"]) == 2
    assert source.status_code == 201

    run = client.post(
        "/runs",
        json={"task": "Analyze sales trends.", "data_source_id": "warehouse-sales"},
    ).json()
    execution = client.post(f"/runs/{run['id']}/execute")

    assert execution.status_code == 200
    assert execution.json()["status"] == "completed"
    assert execution.json()["failed_node_ids"] == []


def test_connector_explorer_is_tenant_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "AEAI_AUTH_TOKEN_PROFILES",
        "acme-token=acme-admin|Acme Admin|admin|acme|finance;"
        "globex-token=globex-admin|Globex Admin|admin|globex|finance",
    )
    root = tmp_path / "datasets"
    root.mkdir()
    client = TestClient(create_app())
    installation = client.post(
        "/connectors/installations",
        headers={"Authorization": "Bearer acme-token"},
        json={
            "connector_id": "local-file",
            "name": "Acme datasets",
            "configuration": {"dataset_root": str(root)},
        },
    ).json()

    response = client.get(
        f"/connectors/installations/{installation['id']}/browse",
        headers={"Authorization": "Bearer globex-token"},
    )

    assert response.status_code == 404


def test_object_connector_browses_and_previews_without_exposing_credentials(monkeypatch):
    class FakeS3Client:
        def head_bucket(self, **kwargs):
            assert kwargs == {"Bucket": "analytics-bucket"}

        def list_objects_v2(self, **kwargs):
            assert kwargs["Bucket"] == "analytics-bucket"
            assert kwargs["Prefix"] == "datasets/"
            return {
                "CommonPrefixes": [{"Prefix": "datasets/finance/"}],
                "Contents": [
                    {"Key": "datasets/sales.csv", "Size": 45},
                    {"Key": "datasets/readme.txt", "Size": 12},
                ],
            }

        def get_object(self, **kwargs):
            assert kwargs["Key"] == "datasets/sales.csv"
            return {"Body": BytesIO(b"region,revenue\nNorth,1200\nSouth,900\n")}

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret-key")
    monkeypatch.setitem(
        sys.modules,
        "boto3",
        SimpleNamespace(client=lambda *_args, **_kwargs: FakeS3Client()),
    )
    client = TestClient(create_app())
    installation = client.post(
        "/connectors/installations",
        json={
            "connector_id": "artifact-store",
            "name": "Analytics objects",
            "credential_reference": "env://AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY",
            "configuration": {
                "bucket": "analytics-bucket",
                "region": "eu-west-1",
                "prefix": "datasets",
            },
        },
    ).json()

    probe = client.post(
        f"/connectors/installations/{installation['id']}/test?probe=true"
    )
    browse = client.get(f"/connectors/installations/{installation['id']}/browse")
    preview = client.post(
        f"/connectors/installations/{installation['id']}/preview",
        json={"asset_id": "datasets/sales.csv", "limit": 1},
    )

    assert probe.json()["status"] == "ok"
    assert [asset["kind"] for asset in browse.json()["assets"]] == [
        "folder",
        "object",
        "object",
    ]
    assert preview.json()["rows"] == [{"region": "North", "revenue": "1200"}]
    assert "access-key" not in browse.text + preview.text
    assert "secret-key" not in browse.text + preview.text


def test_connector_hub_ui_exposes_explorer_and_source_publish_controls():
    client = TestClient(create_app())

    page = client.get("/app/admin")
    script = client.get("/app/admin.js")

    assert page.status_code == 200
    assert 'id="dataExplorerTitle"' in page.text
    assert 'id="sourceForm"' in page.text
    assert "/browse?path=" in script.text
    assert "/preview" in script.text
    assert "/sources" in script.text
    assert "?probe=true" in script.text

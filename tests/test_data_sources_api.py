import sqlite3

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository


def test_data_source_api_registers_local_file_and_validates_it(tmp_path):
    dataset_path = tmp_path / "procurement.csv"
    dataset_path.write_text("supplier,spend_amount\nAcme,100\n", encoding="utf-8")
    client = TestClient(create_app())

    create_response = client.post(
        "/data-sources",
        json={
            "id": "procurement-local",
            "name": "Procurement Local CSV",
            "source_type": "local_file",
            "dataset_uri": str(dataset_path),
            "owner": "data-platform",
            "metadata": {"domain": "procurement"},
        },
    )
    list_response = client.get("/data-sources")
    validation_response = client.post("/data-sources/procurement-local/validate")

    source = create_response.json()
    assert create_response.status_code == 201
    assert source["id"] == "procurement-local"
    assert source["source_type"] == "local_file"
    assert source["connector_id"] == "local-file"
    assert source["credential_profile_id"] == "local-filesystem"
    assert source["latest_validation"]["status"] == "ok"
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == "procurement-local"
    assert validation_response.status_code == 200
    assert validation_response.json()["status"] == "ok"


def test_data_source_api_rejects_missing_local_file_with_actionable_error(tmp_path):
    client = TestClient(create_app())

    response = client.post(
        "/data-sources",
        json={
            "id": "missing-local",
            "name": "Missing Local CSV",
            "source_type": "local_file",
            "dataset_uri": str(tmp_path / "missing.csv"),
            "owner": "data-platform",
        },
    )

    body = response.json()
    assert response.status_code == 400
    assert body["detail"]["status"] == "invalid"
    assert "Upload or mount the file" in body["detail"]["message"]


def test_data_source_api_rejects_duplicate_ids(tmp_path):
    dataset_path = tmp_path / "procurement.csv"
    dataset_path.write_text("supplier,spend_amount\nAcme,100\n", encoding="utf-8")
    client = TestClient(create_app())
    payload = {
        "id": "procurement-local",
        "name": "Procurement Local CSV",
        "source_type": "local_file",
        "dataset_uri": str(dataset_path),
        "owner": "data-platform",
    }

    first_response = client.post("/data-sources", json=payload)
    duplicate_response = client.post("/data-sources", json=payload)

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert "already exists" in duplicate_response.json()["detail"]


def test_data_source_api_registers_sqlite_warehouse_source(tmp_path):
    db_path = tmp_path / "warehouse.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE procurement (supplier TEXT, spend_amount REAL)")
        connection.execute("INSERT INTO procurement VALUES ('Acme', 100)")
    client = TestClient(create_app())

    response = client.post(
        "/data-sources",
        json={
            "id": "procurement-sqlite",
            "name": "Procurement SQLite",
            "source_type": "sqlite",
            "dataset_uri": f"sqlite://{db_path}#procurement",
            "owner": "data-platform",
        },
    )

    body = response.json()
    assert response.status_code == 201
    assert body["connector_id"] == "sqlite-local"
    assert body["latest_validation"]["status"] == "ok"
    assert body["latest_validation"]["details"]["columns"] == [
        "supplier",
        "spend_amount",
    ]


def test_snowflake_style_source_requires_configured_profile(monkeypatch):
    for key in (
        "SNOWFLAKE_ACCOUNT",
        "SNOWFLAKE_USER",
        "SNOWFLAKE_PASSWORD",
        "SNOWFLAKE_WAREHOUSE",
        "SNOWFLAKE_DATABASE",
        "SNOWFLAKE_SCHEMA",
    ):
        monkeypatch.delenv(key, raising=False)
    client = TestClient(create_app())

    response = client.post(
        "/data-sources",
        json={
            "id": "procurement-snowflake",
            "name": "Procurement Snowflake",
            "source_type": "snowflake",
            "dataset_uri": "snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
            "owner": "data-platform",
        },
    )

    body = response.json()
    assert response.status_code == 400
    assert body["detail"]["status"] == "invalid"
    assert "Snowflake source is not configured" in body["detail"]["message"]
    assert "SNOWFLAKE_ACCOUNT" in body["detail"]["details"]["missing_env_keys"]


def test_create_run_can_select_registered_data_source(tmp_path):
    repository = InMemoryRunRepository()
    dataset_path = tmp_path / "procurement.csv"
    dataset_path.write_text("supplier,spend_amount\nAcme,100\n", encoding="utf-8")
    client = TestClient(
        create_app(repository=repository, artifact_root=tmp_path / "artifacts")
    )
    source_response = client.post(
        "/data-sources",
        json={
            "id": "procurement-local",
            "name": "Procurement Local CSV",
            "source_type": "local_file",
            "dataset_uri": str(dataset_path),
            "owner": "finance-ops",
            "metadata": {"domain": "procurement"},
        },
    )

    run_response = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend.",
            "data_source_id": "procurement-local",
            "metadata": {"priority": "demo"},
        },
    )

    body = run_response.json()
    dataset_artifact = next(
        artifact for artifact in body["artifacts"] if artifact["type"] == "dataset"
    )
    assert source_response.status_code == 201
    assert run_response.status_code == 201
    assert body["metadata"]["priority"] == "demo"
    assert body["metadata"]["data_source_id"] == "procurement-local"
    assert body["metadata"]["connector_id"] == "local-file"
    assert dataset_artifact["uri"] == str(dataset_path)
    assert dataset_artifact["metadata"]["data_source_id"] == "procurement-local"
    assert dataset_artifact["metadata"]["owner"] == "finance-ops"


def test_create_run_rejects_unreachable_selected_source(tmp_path):
    dataset_path = tmp_path / "procurement.csv"
    dataset_path.write_text("supplier,spend_amount\nAcme,100\n", encoding="utf-8")
    client = TestClient(create_app())
    client.post(
        "/data-sources",
        json={
            "id": "procurement-local",
            "name": "Procurement Local CSV",
            "source_type": "local_file",
            "dataset_uri": str(dataset_path),
            "owner": "finance-ops",
        },
    )
    dataset_path.unlink()

    response = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend.",
            "data_source_id": "procurement-local",
        },
    )

    body = response.json()
    assert response.status_code == 400
    assert body["detail"]["status"] == "invalid"
    assert "Local dataset does not exist" in body["detail"]["message"]

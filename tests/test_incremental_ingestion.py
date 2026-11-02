import csv
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.connectors.ingestion import IngestionStore, pages


def config(**kwargs):
    return dict(
        id="orders", organization_id="acme", workspace_id="finance", primary_key="id", **kwargs
    )


def test_sql_checkpoint_restart_and_export(tmp_path, monkeypatch):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, amount INTEGER)")
        db.executemany("INSERT INTO orders VALUES (?,?)", [(1, 20), (2, 30)])
    monkeypatch.setenv("TEST_SOURCE_URL", f"sqlite:///{source}")
    job = config(kind="sql", connection_env="TEST_SOURCE_URL", table="orders", cursor_key="id")
    store = IngestionStore(tmp_path / "state.db")
    assert store.sync(job) == 2
    assert IngestionStore(store.path).sync(job, force=True) == 0
    with sqlite3.connect(source) as db:
        db.execute("INSERT INTO orders VALUES (3,40)")
    assert store.sync(job, force=True) == 1
    target = tmp_path / "snapshot.csv"
    store.export_csv(job, target)
    with target.open() as handle:
        assert len(list(csv.DictReader(handle))) == 3


def test_failure_rolls_back_checkpoint_and_data(tmp_path):
    store = IngestionStore(tmp_path / "state.db")

    def broken(config, cursor):
        yield [{"id": 1}], "one"
        raise RuntimeError("source failed")

    with pytest.raises(RuntimeError):
        store.sync(config(), fetch=broken)
    with closing(store.connect()) as db:
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
    assert store.sync(config(), fetch=lambda c, p: [([{"id": 1}], "one")]) == 1


def test_hash_dedup_schedule_and_scopes(tmp_path):
    store = IngestionStore(tmp_path / "state.db")

    def fetch(c, p):
        return [([{"id": 1, "amount": 10}], "one")]

    assert store.sync(config(), fetch=fetch) == 1
    assert store.sync(config(), fetch=fetch, force=True) == 0
    assert store.sync(config(), fetch=lambda c, p: pytest.fail("not due")) == 0
    other = {**config(), "workspace_id": "other"}
    assert store.sync(other, fetch=fetch) == 1
    with pytest.raises(ValueError, match="configuration changed"):
        store.sync({**config(), "primary_key": "different"}, fetch=fetch, force=True)


def test_ingestion_audit_is_admin_and_workspace_scoped(tmp_path, monkeypatch):
    path = tmp_path / "state.db"
    monkeypatch.setenv("AEAI_INGESTION_DB_PATH", str(path))
    IngestionStore(path).sync(config(), fetch=lambda c, p: [([{"id": 1}], "one")])
    monkeypatch.setenv("AEAI_AUTH_MODE", "token")
    monkeypatch.setenv(
        "AEAI_AUTH_TOKEN_PROFILES",
        "a=admin|Admin|admin|acme|finance;b=other|Other|admin|other|finance;"
        "v=viewer|Viewer|viewer|acme|finance",
    )
    client = TestClient(create_app(artifact_root=tmp_path))
    assert client.get("/ingestion/audit").status_code == 401
    assert client.get("/ingestion/audit", headers={"Authorization": "Bearer v"}).status_code == 403
    assert client.get("/ingestion/audit", headers={"Authorization": "Bearer b"}).json() == []
    assert len(client.get("/ingestion/audit", headers={"Authorization": "Bearer a"}).json()) == 1


def test_production_rejects_local_auth(monkeypatch):
    monkeypatch.setenv("AEAI_ENV", "production")
    monkeypatch.setenv("AEAI_AUTH_MODE", "local")
    with pytest.raises(ValueError, match="Production requires"):
        create_app()


def test_rest_rejects_insecure_endpoint():
    with pytest.raises(ValueError, match="HTTPS"):
        list(pages({"kind": "rest", "url": "http://example.com"}, None))


def test_compose_is_valid_and_workers_are_separate():
    from pathlib import Path

    import yaml

    services = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]
    assert {"api", "risk-worker", "workflow-worker", "monitoring-worker"} <= services.keys()
    assert "postgres" in services["api"]["depends_on"]
    assert services["risk-worker"]["depends_on"]["api"]["condition"] == "service_healthy"


def test_s3_etag_and_changed_record(monkeypatch):
    import io
    import sys
    from types import SimpleNamespace

    class Client:
        def head_object(self, **kwargs):
            return {"ETag": "v2", "ContentLength": 16}

        def get_object(self, **kwargs):
            assert kwargs["IfMatch"] == "v2"
            return {"Body": io.BytesIO(b"id,amount\n1,20\n")}

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=lambda kind: Client()))
    job = {"kind": "s3", "bucket": "approved", "key": "orders.csv"}
    assert list(pages(job, "v2")) == []
    assert list(pages(job, "v1")) == [([{"id": "1", "amount": "20"}], "v2")]


def test_rest_cursor_and_redirect_policy(monkeypatch):
    import httpx

    original = httpx.Client

    def respond(request):
        assert request.url.params["cursor"] == "previous"
        return httpx.Response(200, json={"items": [{"id": 1}], "next_cursor": "next"})

    def factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    assert list(pages({"kind": "rest", "url": "https://example.com/changes"}, "previous")) == [
        ([{"id": 1}], "next")
    ]


def test_snowflake_parameterized_checkpoint(monkeypatch):
    import sys
    from types import ModuleType

    module = ModuleType("snowflake.connector")

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, params):
            assert "WHERE ID > %(cursor)s" in query
            assert params == {"cursor": 10}

        def fetchall(self):
            return [{"ID": 11}]

    class Connection(Cursor):
        def cursor(self, kind):
            return Cursor()

    module.connect = lambda **kwargs: Connection()
    module.DictCursor = object
    parent = ModuleType("snowflake")
    parent.connector = module
    monkeypatch.setitem(sys.modules, "snowflake", parent)
    monkeypatch.setitem(sys.modules, "snowflake.connector", module)
    monkeypatch.setenv("TEST_SNOWFLAKE", "{}")
    assert list(
        pages(
            {
                "kind": "snowflake",
                "table": "ORDERS",
                "cursor_key": "ID",
                "connection_env": "TEST_SNOWFLAKE",
            },
            10,
        )
    ) == [([{"ID": 11}], 11)]

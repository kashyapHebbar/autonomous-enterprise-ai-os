from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from aeai_os.data import (
    SnowflakeSettings,
    SnowflakeWarehouseConnector,
    SqliteWarehouseConnector,
    WarehouseConfigurationError,
    WarehouseConnectorError,
    WarehouseDatasetAdapter,
    WarehouseDatasetReference,
    dataset_reference_from_metadata,
    default_warehouse_registry,
)

SNOWFLAKE_ENV = {
    "SNOWFLAKE_ACCOUNT": "account",
    "SNOWFLAKE_USER": "user",
    "SNOWFLAKE_PASSWORD": "secret-password",
    "SNOWFLAKE_WAREHOUSE": "compute_wh",
    "SNOWFLAKE_DATABASE": "analytics",
    "SNOWFLAKE_SCHEMA": "public",
    "SNOWFLAKE_ROLE": "analyst",
}


def build_procurement_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE procurement (
                supplier TEXT,
                category TEXT,
                spend_amount REAL
            )
            """
        )
        connection.executemany(
            "INSERT INTO procurement VALUES (?, ?, ?)",
            [
                ("Acme", "Software", 1200.50),
                ("Zenith", "Hardware", 800.00),
                ("Acme", "Software", 300.00),
            ],
        )


def test_sqlite_connector_supports_preview_schema_and_grouped_sum(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    reference = WarehouseDatasetReference(
        source="sqlite",
        table="procurement",
        database_path=str(db_path),
    )
    connector = SqliteWarehouseConnector(db_path)

    preview = connector.preview_rows(reference, limit=2)
    columns = connector.describe(reference)
    totals = connector.aggregate_sum_by(reference, "supplier", "spend_amount")

    assert [row["supplier"] for row in preview] == ["Acme", "Zenith"]
    assert [(column.name, column.data_type) for column in columns] == [
        ("supplier", "TEXT"),
        ("category", "TEXT"),
        ("spend_amount", "REAL"),
    ]
    assert totals == {"Acme": 1500.5, "Zenith": 800.0}


def test_sqlite_connector_supports_select_query_references(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    reference = WarehouseDatasetReference(
        source="sqlite",
        query="SELECT supplier, spend_amount FROM procurement WHERE category = 'Software'",
        database_path=str(db_path),
    )
    connector = SqliteWarehouseConnector(db_path)

    preview = connector.preview_rows(reference, limit=5)
    columns = connector.describe(reference)

    assert [row["supplier"] for row in preview] == ["Acme", "Acme"]
    assert [column.name for column in columns] == ["supplier", "spend_amount"]


def test_sqlite_connector_supports_parameterized_query_references(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    reference = WarehouseDatasetReference(
        source="sqlite",
        query="SELECT supplier, spend_amount FROM procurement WHERE category = :category",
        database_path=str(db_path),
        parameters={"category": "Software"},
    )
    connector = SqliteWarehouseConnector(db_path)

    preview = connector.preview_rows(reference, limit=5)
    rows = connector.fetch_rows(reference, limit=None)

    assert [row["supplier"] for row in preview] == ["Acme", "Acme"]
    assert [row["supplier"] for row in rows] == ["Acme", "Acme"]


def test_warehouse_dataset_adapter_matches_dataset_query_contract(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    reference = WarehouseDatasetReference(
        source="sqlite",
        table="procurement",
        database_path=str(db_path),
    )
    adapter = WarehouseDatasetAdapter(
        connector=SqliteWarehouseConnector(db_path),
        reference=reference,
    )

    assert adapter.columns() == ["supplier", "category", "spend_amount"]
    assert adapter.preview(limit=1) == [
        {"supplier": "Acme", "category": "Software", "spend_amount": "1200.5"}
    ]
    assert adapter.rows()[1]["supplier"] == "Zenith"
    assert adapter.aggregate_sum_by("supplier", "spend_amount") == {
        "Acme": 1500.5,
        "Zenith": 800.0,
    }


def test_sqlite_connector_rejects_unsafe_identifiers(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    reference = WarehouseDatasetReference(
        source="sqlite",
        table="procurement",
        database_path=str(db_path),
    )
    connector = SqliteWarehouseConnector(db_path)

    with pytest.raises(WarehouseConnectorError, match="Unsafe SQL identifier"):
        connector.aggregate_sum_by(reference, "supplier;DROP_TABLE", "spend_amount")


def test_dataset_reference_helpers_and_registry_select_sqlite_connector(tmp_path):
    db_path = tmp_path / "warehouse.db"
    build_procurement_db(db_path)
    info = dataset_reference_from_metadata(
        f"sqlite://{db_path}#procurement",
        {"source": "warehouse"},
    )

    registry = default_warehouse_registry()
    connector = registry.connector_for_reference(info.warehouse)

    assert info.kind == "warehouse"
    assert info.warehouse.table == "procurement"
    assert info.warehouse.database_path == str(db_path)
    assert isinstance(connector, SqliteWarehouseConnector)
    assert connector.preview_rows(info.warehouse, limit=1)[0]["supplier"] == "Acme"


def test_dataset_reference_helpers_distinguish_local_files(tmp_path):
    csv_path = tmp_path / "procurement.csv"
    info = dataset_reference_from_metadata(str(csv_path), {"format": "csv"})

    assert info.kind == "local_file"
    assert info.format == "csv"
    assert info.warehouse is None


def test_dataset_reference_helpers_parse_snowflake_uri():
    info = dataset_reference_from_metadata(
        "snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
        {"source": "warehouse"},
    )

    assert info.kind == "warehouse"
    assert info.warehouse.source == "snowflake"
    assert info.warehouse.database == "ANALYTICS"
    assert info.warehouse.schema == "PUBLIC"
    assert info.warehouse.table == "PROCUREMENT"


def test_dataset_reference_helpers_parse_query_parameters():
    info = dataset_reference_from_metadata(
        "snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
        {
            "source": "warehouse",
            "query_parameters": {"category": "Software"},
        },
    )

    assert info.kind == "warehouse"
    assert info.warehouse.parameters == {"category": "Software"}

    with pytest.raises(WarehouseConnectorError, match="query_parameters must be a mapping"):
        dataset_reference_from_metadata(
            "snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
            {"source": "warehouse", "query_parameters": ["category"]},
        )


def test_snowflake_settings_from_env_validates_required_keys_and_options():
    with pytest.raises(WarehouseConfigurationError, match="SNOWFLAKE_ACCOUNT"):
        SnowflakeSettings.from_env({})

    settings = SnowflakeSettings.from_env(
        {
            **SNOWFLAKE_ENV,
            "SNOWFLAKE_CONNECT_TIMEOUT_SECONDS": "7",
            "SNOWFLAKE_QUERY_TIMEOUT_SECONDS": "25",
            "SNOWFLAKE_ROW_LIMIT": "500",
            "SNOWFLAKE_APPLICATION": "aeai-test",
        }
    )

    assert settings.account == "account"
    assert settings.role == "analyst"
    assert settings.connect_timeout_seconds == 7
    assert settings.query_timeout_seconds == 25
    assert settings.row_limit == 500
    assert settings.application == "aeai-test"
    assert "secret-password" not in repr(settings)


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("SNOWFLAKE_ROW_LIMIT", "0", "positive integer"),
        ("SNOWFLAKE_QUERY_TIMEOUT_SECONDS", "not-a-number", "positive integer"),
        ("SNOWFLAKE_WAREHOUSE", "bad-warehouse", "SNOWFLAKE_WAREHOUSE"),
    ],
)
def test_snowflake_settings_reject_invalid_options(key, value, match):
    with pytest.raises(WarehouseConfigurationError, match=match):
        SnowflakeSettings.from_env({**SNOWFLAKE_ENV, key: value})


class FakeSnowflakeCursor:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        description: list[tuple[str, str]] | None = None,
    ) -> None:
        self.rows = rows or [{"SUPPLIER": "Acme"}]
        self.description = description or [("SUPPLIER", "TEXT")]
        self.executions: list[tuple[str, Any, dict[str, Any]]] = []
        self.closed = False

    def execute(self, query: str, parameters=None, **kwargs) -> None:
        self.executions.append((query, parameters, kwargs))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class FakeSnowflakeConnection:
    def __init__(self, cursor: FakeSnowflakeCursor) -> None:
        self.cursor_instance = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_snowflake_connector_uses_parameterized_preview_query_and_runtime_options():
    cursor = FakeSnowflakeCursor()
    connection = FakeSnowflakeConnection(cursor)
    captured_kwargs: dict[str, Any] = {}

    def connection_factory(**kwargs):
        captured_kwargs.update(kwargs)
        return connection

    connector = SnowflakeWarehouseConnector(
        SnowflakeSettings(
            account="account",
            user="user",
            password="password",
            warehouse="compute_wh",
            database="analytics",
            schema="public",
            connect_timeout_seconds=3,
            query_timeout_seconds=12,
            row_limit=5,
            application="aeai-test",
        ),
        connection_factory=connection_factory,
    )
    reference = WarehouseDatasetReference(
        source="snowflake",
        query="SELECT SUPPLIER FROM PROCUREMENT WHERE CATEGORY = %(category)s",
        parameters={"category": "Software"},
    )

    preview = connector.preview_rows(reference, limit=100)

    assert preview == [{"SUPPLIER": "Acme"}]
    assert cursor.executions == [
        (
            "SELECT * FROM "
            "(SELECT SUPPLIER FROM PROCUREMENT WHERE CATEGORY = %(category)s) "
            "AS warehouse_source LIMIT %(_aeai_limit)s",
            {"category": "Software", "_aeai_limit": 5},
            {"timeout": 12},
        )
    ]
    assert captured_kwargs["login_timeout"] == 3
    assert captured_kwargs["network_timeout"] == 3
    assert captured_kwargs["application"] == "aeai-test"
    assert captured_kwargs["session_parameters"] == {
        "QUERY_TAG": "aeai-test",
        "STATEMENT_TIMEOUT_IN_SECONDS": 12,
    }
    assert cursor.closed is True
    assert connection.closed is True


def test_snowflake_connector_describes_query_refs_with_parameters():
    cursor = FakeSnowflakeCursor(description=[("SUPPLIER", "TEXT"), ("SPEND", "NUMBER")])
    connector = SnowflakeWarehouseConnector(
        SnowflakeSettings(
            account="account",
            user="user",
            password="password",
            warehouse="compute_wh",
            database="analytics",
            schema="public",
        ),
        connection_factory=lambda **_kwargs: FakeSnowflakeConnection(cursor),
    )
    reference = WarehouseDatasetReference(
        source="snowflake",
        query="WITH filtered AS (SELECT * FROM PROCUREMENT WHERE CATEGORY = %(category)s) "
        "SELECT SUPPLIER, SPEND FROM filtered",
        parameters={"category": "Software"},
    )

    columns = connector.describe(reference)

    assert [column.name for column in columns] == ["SUPPLIER", "SPEND"]
    assert cursor.executions[0] == (
        "SELECT * FROM "
        "(WITH filtered AS (SELECT * FROM PROCUREMENT WHERE CATEGORY = %(category)s) "
        "SELECT SUPPLIER, SPEND FROM filtered) AS warehouse_source "
        "LIMIT %(_aeai_limit)s",
        {"category": "Software", "_aeai_limit": 0},
        {"timeout": 60},
    )


def test_snowflake_connector_rejects_unsafe_queries_and_identifiers():
    connector = SnowflakeWarehouseConnector(
        SnowflakeSettings(
            account="account",
            user="user",
            password="password",
            warehouse="compute_wh",
            database="analytics",
            schema="public",
        ),
        connection_factory=lambda **_kwargs: FakeSnowflakeConnection(FakeSnowflakeCursor()),
    )

    with pytest.raises(WarehouseConnectorError, match="Unsafe SQL identifier"):
        connector.preview_rows(WarehouseDatasetReference(source="snowflake", table="BAD;DROP"))

    with pytest.raises(WarehouseConnectorError, match="single SELECT or WITH"):
        connector.preview_rows(
            WarehouseDatasetReference(source="snowflake", query="DELETE FROM PROCUREMENT")
        )

    with pytest.raises(WarehouseConnectorError, match="single SELECT, WITH, SHOW, or DESCRIBE"):
        connector.execute_query("DELETE FROM PROCUREMENT")

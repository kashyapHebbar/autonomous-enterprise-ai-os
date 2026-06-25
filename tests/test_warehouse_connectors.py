from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from aeai_os.data import (
    SnowflakeSettings,
    SnowflakeWarehouseConnector,
    SqliteWarehouseConnector,
    WarehouseColumn,
    WarehouseConfigurationError,
    WarehouseConnectorError,
    WarehouseDatasetAdapter,
    WarehouseDatasetReference,
    WarehouseQueryResult,
    dataset_reference_from_metadata,
    default_warehouse_registry,
)


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


def test_snowflake_settings_from_env_validates_required_keys():
    with pytest.raises(WarehouseConfigurationError, match="SNOWFLAKE_ACCOUNT"):
        SnowflakeSettings.from_env({})

    settings = SnowflakeSettings.from_env(
        {
            "SNOWFLAKE_ACCOUNT": "account",
            "SNOWFLAKE_USER": "user",
            "SNOWFLAKE_PASSWORD": "password",
            "SNOWFLAKE_WAREHOUSE": "compute_wh",
            "SNOWFLAKE_DATABASE": "analytics",
            "SNOWFLAKE_SCHEMA": "public",
            "SNOWFLAKE_ROLE": "analyst",
        }
    )

    assert settings.account == "account"
    assert settings.role == "analyst"


def test_snowflake_connector_uses_parameterized_preview_query():
    class CapturingSnowflakeConnector(SnowflakeWarehouseConnector):
        def __init__(self) -> None:
            super().__init__(
                SnowflakeSettings(
                    account="account",
                    user="user",
                    password="password",
                    warehouse="compute_wh",
                    database="analytics",
                    schema="public",
                )
            )
            self.calls: list[tuple[str, Any]] = []

        def execute_query(self, query: str, parameters=None) -> WarehouseQueryResult:
            self.calls.append((query, parameters))
            return WarehouseQueryResult(
                rows=[{"SUPPLIER": "Acme"}],
                columns=[WarehouseColumn(name="SUPPLIER", data_type="TEXT")],
            )

    connector = CapturingSnowflakeConnector()
    reference = WarehouseDatasetReference(
        source="snowflake",
        table="PROCUREMENT",
        database="ANALYTICS",
        schema="PUBLIC",
    )

    preview = connector.preview_rows(reference, limit=7)

    assert preview == [{"SUPPLIER": "Acme"}]
    assert connector.calls == [
        ("SELECT * FROM ANALYTICS.PUBLIC.PROCUREMENT LIMIT %(limit)s", {"limit": 7})
    ]

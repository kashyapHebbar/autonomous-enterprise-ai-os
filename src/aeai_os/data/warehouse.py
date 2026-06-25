from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, unquote, urlparse

from aeai_os.data.profiling import DataIngestionError

ParameterSet = Sequence[Any] | Mapping[str, Any] | None


class WarehouseConnectorError(DataIngestionError):
    """Raised when a warehouse connector cannot resolve or query a dataset."""


class WarehouseConfigurationError(WarehouseConnectorError):
    """Raised when a connector is missing required configuration."""


@dataclass(frozen=True)
class WarehouseColumn:
    name: str
    data_type: str
    nullable: bool | None = None


@dataclass(frozen=True)
class WarehouseQueryResult:
    rows: list[dict[str, Any]]
    columns: list[WarehouseColumn]


@dataclass(frozen=True)
class WarehouseDatasetReference:
    source: str
    table: str | None = None
    query: str | None = None
    database: str | None = None
    schema: str | None = None
    database_path: str | None = None
    uri: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if bool(self.table) == bool(self.query):
            raise WarehouseConnectorError(
                "Warehouse dataset reference must include exactly one of table or query."
            )

    @property
    def normalized_source(self) -> str:
        return self.source.strip().lower().replace("-", "_")

    @property
    def qualified_table(self) -> str:
        if not self.table:
            raise WarehouseConnectorError("Warehouse dataset reference does not include a table.")
        if "." in self.table or not (self.database or self.schema):
            return self.table
        parts = [part for part in [self.database, self.schema, self.table] if part]
        return ".".join(parts)


@dataclass(frozen=True)
class DatasetReferenceInfo:
    kind: Literal["local_file", "warehouse"]
    uri: str
    format: str | None = None
    warehouse: WarehouseDatasetReference | None = None


class WarehouseConnector(Protocol):
    source: str

    def preview_rows(
        self, reference: WarehouseDatasetReference, limit: int = 10
    ) -> list[dict[str, Any]]: ...

    def describe(self, reference: WarehouseDatasetReference) -> list[WarehouseColumn]: ...

    def aggregate_sum_by(
        self,
        reference: WarehouseDatasetReference,
        group_column: str,
        value_column: str,
        limit: int | None = None,
    ) -> dict[str, float]: ...

    def execute_query(
        self, query: str, parameters: ParameterSet = None
    ) -> WarehouseQueryResult: ...


class SqliteWarehouseConnector:
    source = "sqlite"

    def __init__(self, database_path: str | Path) -> None:
        if not str(database_path):
            raise WarehouseConfigurationError(
                "SQLite warehouse connector requires a database path."
            )
        self.database_path = Path(database_path)

    @classmethod
    def from_reference(cls, reference: WarehouseDatasetReference) -> SqliteWarehouseConnector:
        if not reference.database_path:
            raise WarehouseConfigurationError(
                "SQLite warehouse reference requires database_path metadata or a sqlite:// URI."
            )
        return cls(reference.database_path)

    def preview_rows(
        self, reference: WarehouseDatasetReference, limit: int = 10
    ) -> list[dict[str, Any]]:
        query = f"SELECT * FROM {self._source_sql(reference)} LIMIT :limit"
        return self.execute_query(query, {"limit": max(limit, 0)}).rows

    def describe(self, reference: WarehouseDatasetReference) -> list[WarehouseColumn]:
        if reference.table and _is_simple_identifier(reference.table):
            table_name = _quote_sqlite_string(reference.table)
            rows = self.execute_query(f"PRAGMA table_info({table_name})").rows
            return [
                WarehouseColumn(
                    name=str(row["name"]),
                    data_type=str(row["type"] or "unknown"),
                    nullable=not bool(row["notnull"]),
                )
                for row in rows
            ]

        result = self.execute_query(f"SELECT * FROM {self._source_sql(reference)} LIMIT 0")
        return result.columns

    def aggregate_sum_by(
        self,
        reference: WarehouseDatasetReference,
        group_column: str,
        value_column: str,
        limit: int | None = None,
    ) -> dict[str, float]:
        group_sql = _sql_identifier(group_column, allow_dotted=False)
        value_sql = _sql_identifier(value_column, allow_dotted=False)
        limit_clause = " LIMIT :limit" if limit is not None else ""
        parameters = {"limit": max(limit or 0, 0)} if limit is not None else None
        query = (
            "SELECT "
            f"COALESCE(CAST({group_sql} AS TEXT), '<missing>') AS group_key, "
            f"SUM(CAST({value_sql} AS REAL)) AS total "
            f"FROM {self._source_sql(reference)} "
            f"WHERE {value_sql} IS NOT NULL "
            f"GROUP BY {group_sql} "
            "ORDER BY group_key"
            f"{limit_clause}"
        )
        rows = self.execute_query(query, parameters).rows
        return {str(row["group_key"]): float(row["total"] or 0.0) for row in rows}

    def execute_query(self, query: str, parameters: ParameterSet = None) -> WarehouseQueryResult:
        if not self.database_path.exists():
            raise WarehouseConnectorError(
                f"SQLite warehouse database does not exist: {self.database_path}"
            )

        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, parameters or {})
            rows = [dict(row) for row in cursor.fetchall()]
            columns = [
                WarehouseColumn(name=str(column[0]), data_type="unknown", nullable=None)
                for column in (cursor.description or [])
            ]
        return WarehouseQueryResult(rows=rows, columns=columns)

    def _source_sql(self, reference: WarehouseDatasetReference) -> str:
        _assert_source(reference, self.source)
        if reference.table:
            return _sql_identifier(reference.qualified_table)
        return f"({_select_query(reference.query)}) AS warehouse_source"


@dataclass(frozen=True)
class SnowflakeSettings:
    account: str
    user: str
    password: str
    warehouse: str
    database: str
    schema: str
    role: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SnowflakeSettings:
        values = os.environ if env is None else env
        required = {
            "SNOWFLAKE_ACCOUNT": values.get("SNOWFLAKE_ACCOUNT", "").strip(),
            "SNOWFLAKE_USER": values.get("SNOWFLAKE_USER", "").strip(),
            "SNOWFLAKE_PASSWORD": values.get("SNOWFLAKE_PASSWORD", "").strip(),
            "SNOWFLAKE_WAREHOUSE": values.get("SNOWFLAKE_WAREHOUSE", "").strip(),
            "SNOWFLAKE_DATABASE": values.get("SNOWFLAKE_DATABASE", "").strip(),
            "SNOWFLAKE_SCHEMA": values.get("SNOWFLAKE_SCHEMA", "").strip(),
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise WarehouseConfigurationError(
                "Missing Snowflake connector configuration: " + ", ".join(missing)
            )
        return cls(
            account=required["SNOWFLAKE_ACCOUNT"],
            user=required["SNOWFLAKE_USER"],
            password=required["SNOWFLAKE_PASSWORD"],
            warehouse=required["SNOWFLAKE_WAREHOUSE"],
            database=required["SNOWFLAKE_DATABASE"],
            schema=required["SNOWFLAKE_SCHEMA"],
            role=values.get("SNOWFLAKE_ROLE") or None,
        )


class SnowflakeWarehouseConnector:
    source = "snowflake"

    def __init__(self, settings: SnowflakeSettings) -> None:
        self.settings = settings

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SnowflakeWarehouseConnector:
        return cls(SnowflakeSettings.from_env(env))

    def preview_rows(
        self, reference: WarehouseDatasetReference, limit: int = 10
    ) -> list[dict[str, Any]]:
        query = f"SELECT * FROM {self._source_sql(reference)} LIMIT %(limit)s"
        return self.execute_query(query, {"limit": max(limit, 0)}).rows

    def describe(self, reference: WarehouseDatasetReference) -> list[WarehouseColumn]:
        if reference.table:
            rows = self.execute_query(f"DESCRIBE TABLE {self._source_sql(reference)}").rows
            return [
                WarehouseColumn(
                    name=str(row.get("name") or row.get("NAME") or ""),
                    data_type=str(row.get("type") or row.get("TYPE") or "unknown"),
                    nullable=_snowflake_nullable(row),
                )
                for row in rows
                if row.get("name") or row.get("NAME")
            ]

        result = self.execute_query(
            f"SELECT * FROM {self._source_sql(reference)} LIMIT %(limit)s",
            {"limit": 0},
        )
        return result.columns

    def aggregate_sum_by(
        self,
        reference: WarehouseDatasetReference,
        group_column: str,
        value_column: str,
        limit: int | None = None,
    ) -> dict[str, float]:
        group_sql = _sql_identifier(group_column, allow_dotted=False)
        value_sql = _sql_identifier(value_column, allow_dotted=False)
        limit_clause = " LIMIT %(limit)s" if limit is not None else ""
        parameters = {"limit": max(limit or 0, 0)} if limit is not None else None
        query = (
            "SELECT "
            f"COALESCE(CAST({group_sql} AS VARCHAR), '<missing>') AS group_key, "
            f"SUM(TRY_TO_DOUBLE({value_sql})) AS total "
            f"FROM {self._source_sql(reference)} "
            f"WHERE {value_sql} IS NOT NULL "
            f"GROUP BY {group_sql} "
            "ORDER BY group_key"
            f"{limit_clause}"
        )
        rows = self.execute_query(query, parameters).rows
        return {
            str(row["GROUP_KEY"] if "GROUP_KEY" in row else row["group_key"]): _row_total(row)
            for row in rows
        }

    def execute_query(self, query: str, parameters: ParameterSet = None) -> WarehouseQueryResult:
        try:
            import snowflake.connector
            from snowflake.connector import DictCursor
        except ImportError as exc:
            raise WarehouseConfigurationError(
                "Snowflake connector package is not installed. Install snowflake-connector-python "
                "before executing Snowflake-backed datasets."
            ) from exc

        connection = snowflake.connector.connect(
            account=self.settings.account,
            user=self.settings.user,
            password=self.settings.password,
            warehouse=self.settings.warehouse,
            database=self.settings.database,
            schema=self.settings.schema,
            role=self.settings.role,
        )
        cursor = connection.cursor(DictCursor)
        try:
            cursor.execute(query, parameters or None)
            rows = [dict(row) for row in cursor.fetchall()]
            columns = [
                WarehouseColumn(name=str(column[0]), data_type=str(column[1]), nullable=None)
                for column in (cursor.description or [])
            ]
            return WarehouseQueryResult(rows=rows, columns=columns)
        finally:
            cursor.close()
            connection.close()

    def _source_sql(self, reference: WarehouseDatasetReference) -> str:
        _assert_source(reference, self.source)
        if reference.table:
            return _sql_identifier(reference.qualified_table)
        return f"({_select_query(reference.query)}) AS warehouse_source"


ConnectorFactory = Callable[[WarehouseDatasetReference], WarehouseConnector]


class WarehouseConnectorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ConnectorFactory] = {}

    def register(self, source: str, connector: WarehouseConnector) -> None:
        normalized = _normalize_source(source)
        self._factories[normalized] = lambda _reference: connector

    def register_factory(self, source: str, factory: ConnectorFactory) -> None:
        self._factories[_normalize_source(source)] = factory

    def get(
        self, source: str, reference: WarehouseDatasetReference | None = None
    ) -> WarehouseConnector:
        normalized = _normalize_source(source)
        try:
            factory = self._factories[normalized]
        except KeyError as exc:
            raise WarehouseConnectorError(
                f"No warehouse connector registered for source: {source}"
            ) from exc
        if reference is None:
            reference = WarehouseDatasetReference(source=normalized, table="_registry_probe")
        return factory(reference)

    def connector_for_reference(self, reference: WarehouseDatasetReference) -> WarehouseConnector:
        return self.get(reference.normalized_source, reference)


def default_warehouse_registry(env: Mapping[str, str] | None = None) -> WarehouseConnectorRegistry:
    registry = WarehouseConnectorRegistry()
    registry.register_factory("sqlite", SqliteWarehouseConnector.from_reference)
    registry.register_factory(
        "snowflake", lambda _reference: SnowflakeWarehouseConnector.from_env(env)
    )
    return registry


def dataset_reference_from_metadata(
    uri: str, metadata: Mapping[str, Any] | None = None
) -> DatasetReferenceInfo:
    metadata = metadata or {}
    if is_warehouse_dataset(uri, metadata):
        warehouse = warehouse_reference_from_metadata(uri, metadata)
        return DatasetReferenceInfo(kind="warehouse", uri=uri, warehouse=warehouse)
    dataset_format = (
        str(metadata.get("format")) if metadata.get("format") else Path(uri).suffix.lstrip(".")
    )
    return DatasetReferenceInfo(kind="local_file", uri=uri, format=dataset_format)


def is_warehouse_dataset(uri: str | None, metadata: Mapping[str, Any] | None = None) -> bool:
    metadata = metadata or {}
    source = _metadata_source(metadata)
    if source in {"sqlite", "snowflake"}:
        return True
    if str(metadata.get("source", "")).strip().lower() == "warehouse":
        return True
    if uri:
        return urlparse(uri).scheme.lower() in {"sqlite", "snowflake"}
    return False


def warehouse_reference_from_metadata(
    uri: str | None, metadata: Mapping[str, Any] | None = None
) -> WarehouseDatasetReference:
    metadata = metadata or {}
    parsed = urlparse(uri or "")
    uri_source = parsed.scheme.lower() if parsed.scheme.lower() in {"sqlite", "snowflake"} else None
    source = _metadata_source(metadata) or uri_source
    if not source:
        raise WarehouseConnectorError("Dataset metadata does not identify a warehouse source.")

    table = _metadata_value(metadata, "table", "warehouse_table")
    query = _metadata_value(metadata, "query", "warehouse_query")
    database = _metadata_value(metadata, "database", "warehouse_database")
    schema = _metadata_value(metadata, "schema", "warehouse_schema")
    database_path = _metadata_value(metadata, "database_path", "sqlite_path")

    if source == "sqlite" and parsed.scheme.lower() == "sqlite":
        database_path = database_path or _sqlite_path_from_uri(parsed)
        table = table or unquote(parsed.fragment or "")
        table = table or parse_qs(parsed.query).get("table", [""])[0] or None
        query = query or parse_qs(parsed.query).get("query", [""])[0] or None

    if source == "snowflake" and parsed.scheme.lower() == "snowflake":
        relation = _snowflake_relation_from_uri(parsed)
        if relation and not table:
            database, schema, table = relation
        query = query or parse_qs(parsed.query).get("query", [""])[0] or None

    return WarehouseDatasetReference(
        source=source,
        table=table,
        query=query,
        database=database,
        schema=schema,
        database_path=database_path,
        uri=uri,
        metadata=metadata,
    )


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _assert_source(reference: WarehouseDatasetReference, expected: str) -> None:
    if reference.normalized_source != expected:
        raise WarehouseConnectorError(
            f"{expected} connector cannot query {reference.source} warehouse references."
        )


def _is_simple_identifier(identifier: str) -> bool:
    return _IDENTIFIER_RE.fullmatch(identifier) is not None


def _metadata_source(metadata: Mapping[str, Any]) -> str | None:
    candidates = [
        metadata.get("warehouse"),
        metadata.get("warehouse_source"),
        metadata.get("adapter"),
        metadata.get("source"),
    ]
    for candidate in candidates:
        normalized = _normalize_source(str(candidate)) if candidate else ""
        if normalized in {"sqlite", "snowflake"}:
            return normalized
    return None


def _metadata_value(metadata: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _normalize_source(source: str) -> str:
    return source.strip().lower().replace("-", "_")


def _quote_sqlite_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _row_total(row: Mapping[str, Any]) -> float:
    value = row.get("TOTAL") if "TOTAL" in row else row.get("total")
    return float(value or 0.0)


def _select_query(query: str | None) -> str:
    if not query or not query.strip():
        raise WarehouseConnectorError("Warehouse dataset query cannot be empty.")
    normalized = query.strip().lower()
    if not normalized.startswith("select") or ";" in normalized:
        raise WarehouseConnectorError("Warehouse dataset query must be a single SELECT statement.")
    return query.strip()


def _snowflake_nullable(row: Mapping[str, Any]) -> bool | None:
    raw_value = row.get("null?") or row.get("NULL?") or row.get("nullable") or row.get("NULLABLE")
    if raw_value is None:
        return None
    return str(raw_value).strip().upper() in {"Y", "YES", "TRUE"}


def _snowflake_relation_from_uri(parsed: Any) -> tuple[str | None, str | None, str] | None:
    raw_relation = ".".join(part for part in [parsed.netloc, parsed.path.strip("/")] if part)
    if not raw_relation:
        return None
    parts = [unquote(part) for part in raw_relation.replace("/", ".").split(".") if part]
    if len(parts) == 1:
        return None, None, parts[0]
    if len(parts) == 2:
        return None, parts[0], parts[1]
    return parts[-3], parts[-2], parts[-1]


def _sqlite_path_from_uri(parsed: Any) -> str | None:
    if parsed.netloc and parsed.netloc != "localhost":
        return unquote(f"//{parsed.netloc}{parsed.path}")
    return unquote(parsed.path)


def _sql_identifier(identifier: str, *, allow_dotted: bool = True) -> str:
    parts = identifier.split(".") if allow_dotted else [identifier]
    if not parts or any(not _IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise WarehouseConnectorError(f"Unsafe SQL identifier: {identifier}")
    return ".".join(parts)

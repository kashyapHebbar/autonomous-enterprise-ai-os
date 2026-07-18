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
from aeai_os.observability.tracing import start_span

ParameterSet = Sequence[Any] | Mapping[str, Any] | None
SnowflakeConnectionFactory = Callable[..., Any]
_INTERNAL_LIMIT_PARAMETER = "_aeai_limit"


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
    credential_profile_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if bool(self.table) == bool(self.query):
            raise WarehouseConnectorError(
                "Warehouse dataset reference must include exactly one of table or query."
            )
        if not isinstance(self.parameters, Mapping):
            raise WarehouseConnectorError("Warehouse query parameters must be a mapping.")

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

    def fetch_rows(
        self, reference: WarehouseDatasetReference, limit: int | None = None
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
        return self.fetch_rows(reference, limit=max(limit, 0))

    def fetch_rows(
        self, reference: WarehouseDatasetReference, limit: int | None = None
    ) -> list[dict[str, Any]]:
        limit_clause = f" LIMIT :{_INTERNAL_LIMIT_PARAMETER}" if limit is not None else ""
        parameters = (
            _merge_parameters(reference.parameters, {_INTERNAL_LIMIT_PARAMETER: max(limit or 0, 0)})
            if limit is not None
            else dict(reference.parameters)
        )
        if limit is None:
            query = f"SELECT * FROM {self._source_sql(reference)}"
        else:
            query = f"SELECT * FROM {self._source_sql(reference)}{limit_clause}"
        return self.execute_query(query, parameters or None).rows

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

        result = self.execute_query(
            f"SELECT * FROM {self._source_sql(reference)} LIMIT 0",
            dict(reference.parameters) or None,
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
        limit_clause = f" LIMIT :{_INTERNAL_LIMIT_PARAMETER}" if limit is not None else ""
        parameters = (
            _merge_parameters(reference.parameters, {_INTERNAL_LIMIT_PARAMETER: max(limit or 0, 0)})
            if limit is not None
            else dict(reference.parameters)
        )
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
        rows = self.execute_query(query, parameters or None).rows
        return {str(row["group_key"]): float(row["total"] or 0.0) for row in rows}

    def execute_query(self, query: str, parameters: ParameterSet = None) -> WarehouseQueryResult:
        with start_span(
            "connector.sqlite.query",
            {
                "connector.provider": self.source,
                "connector.operation": "execute_query",
                "db.system": "sqlite",
                "db.statement.length": len(query),
                "db.parameters.count": _parameter_count(parameters),
            },
        ) as span:
            if not self.database_path.exists():
                span.set_attribute("error", True)
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
            span.set_attribute("db.rows_returned", len(rows))
            span.set_attribute("db.columns_returned", len(columns))
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
    password: str = field(repr=False)
    warehouse: str
    database: str
    schema: str
    role: str | None = None
    connect_timeout_seconds: int = 15
    query_timeout_seconds: int = 60
    row_limit: int = 10_000
    application: str = "aeai-os"

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
        role = values.get("SNOWFLAKE_ROLE", "").strip() or None
        return cls(
            account=required["SNOWFLAKE_ACCOUNT"],
            user=required["SNOWFLAKE_USER"],
            password=required["SNOWFLAKE_PASSWORD"],
            warehouse=_snowflake_identifier(
                required["SNOWFLAKE_WAREHOUSE"], "SNOWFLAKE_WAREHOUSE"
            ),
            database=_snowflake_identifier(
                required["SNOWFLAKE_DATABASE"], "SNOWFLAKE_DATABASE"
            ),
            schema=_snowflake_identifier(required["SNOWFLAKE_SCHEMA"], "SNOWFLAKE_SCHEMA"),
            role=_snowflake_identifier(role, "SNOWFLAKE_ROLE") if role else None,
            connect_timeout_seconds=_parse_positive_int(
                values, "SNOWFLAKE_CONNECT_TIMEOUT_SECONDS", 15
            ),
            query_timeout_seconds=_parse_positive_int(
                values, "SNOWFLAKE_QUERY_TIMEOUT_SECONDS", 60
            ),
            row_limit=_parse_positive_int(values, "SNOWFLAKE_ROW_LIMIT", 10_000),
            application=values.get("SNOWFLAKE_APPLICATION", "").strip() or "aeai-os",
        )


class SnowflakeWarehouseConnector:
    source = "snowflake"

    def __init__(
        self,
        settings: SnowflakeSettings,
        connection_factory: SnowflakeConnectionFactory | None = None,
    ) -> None:
        self.settings = settings
        self._connection_factory = connection_factory

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        connection_factory: SnowflakeConnectionFactory | None = None,
    ) -> SnowflakeWarehouseConnector:
        return cls(SnowflakeSettings.from_env(env), connection_factory=connection_factory)

    def preview_rows(
        self, reference: WarehouseDatasetReference, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self.fetch_rows(reference, limit=max(limit, 0))

    def fetch_rows(
        self, reference: WarehouseDatasetReference, limit: int | None = None
    ) -> list[dict[str, Any]]:
        effective_limit = self._bounded_limit(limit)
        parameters = _merge_parameters(
            reference.parameters, {_INTERNAL_LIMIT_PARAMETER: effective_limit}
        )
        query = (
            f"SELECT * FROM {self._source_sql(reference)} "
            f"LIMIT %({_INTERNAL_LIMIT_PARAMETER})s"
        )
        return self.execute_query(query, parameters or None).rows

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
            f"SELECT * FROM {self._source_sql(reference)} LIMIT %({_INTERNAL_LIMIT_PARAMETER})s",
            _merge_parameters(reference.parameters, {_INTERNAL_LIMIT_PARAMETER: 0}),
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
        limit_clause = f" LIMIT %({_INTERNAL_LIMIT_PARAMETER})s" if limit is not None else ""
        parameters = (
            _merge_parameters(
                reference.parameters, {_INTERNAL_LIMIT_PARAMETER: self._bounded_limit(limit)}
            )
            if limit is not None
            else dict(reference.parameters)
        )
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
        rows = self.execute_query(query, parameters or None).rows
        return {
            str(row["GROUP_KEY"] if "GROUP_KEY" in row else row["group_key"]): _row_total(row)
            for row in rows
        }

    def execute_query(self, query: str, parameters: ParameterSet = None) -> WarehouseQueryResult:
        statement = _snowflake_statement(query)
        with start_span(
            "connector.snowflake.query",
            {
                "connector.provider": self.source,
                "connector.operation": "execute_query",
                "credential_profile.id": "snowflake-default",
                "db.system": "snowflake",
                "db.name": self.settings.database,
                "db.schema": self.settings.schema,
                "db.statement.length": len(statement),
                "db.parameters.count": _parameter_count(parameters),
            },
        ) as span:
            connection = None
            cursor = None
            try:
                if self._connection_factory:
                    connection = self._connection_factory(**self._connection_kwargs())
                    cursor = connection.cursor()
                else:
                    try:
                        import snowflake.connector
                        from snowflake.connector import DictCursor
                    except ImportError as exc:
                        span.set_attribute("error", True)
                        raise WarehouseConfigurationError(
                            "Snowflake connector package is not installed. Install "
                            "snowflake-connector-python before executing Snowflake-backed "
                            "datasets."
                        ) from exc

                    connection = snowflake.connector.connect(**self._connection_kwargs())
                    cursor = connection.cursor(DictCursor)

                cursor.execute(
                    statement,
                    parameters or None,
                    timeout=self.settings.query_timeout_seconds,
                )
                rows = [dict(row) for row in cursor.fetchall()]
                columns = [
                    WarehouseColumn(name=str(column[0]), data_type=str(column[1]), nullable=None)
                    for column in (cursor.description or [])
                ]
                span.set_attribute("db.rows_returned", len(rows))
                span.set_attribute("db.columns_returned", len(columns))
                return WarehouseQueryResult(rows=rows, columns=columns)
            except WarehouseConnectorError:
                span.set_attribute("error", True)
                raise
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("error", True)
                raise WarehouseConnectorError(f"Snowflake query execution failed: {exc}") from exc
            finally:
                _close_resource(cursor)
                _close_resource(connection)

    def _source_sql(self, reference: WarehouseDatasetReference) -> str:
        _assert_source(reference, self.source)
        if reference.table:
            return _sql_identifier(reference.qualified_table)
        return f"({_select_query(reference.query)}) AS warehouse_source"

    def _bounded_limit(self, limit: int | None) -> int:
        requested = self.settings.row_limit if limit is None else max(limit, 0)
        return min(requested, self.settings.row_limit)

    def _connection_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "account": self.settings.account,
            "user": self.settings.user,
            "password": self.settings.password,
            "warehouse": self.settings.warehouse,
            "database": self.settings.database,
            "schema": self.settings.schema,
            "login_timeout": self.settings.connect_timeout_seconds,
            "network_timeout": self.settings.connect_timeout_seconds,
            "application": self.settings.application,
            "session_parameters": {
                "QUERY_TAG": self.settings.application,
                "STATEMENT_TIMEOUT_IN_SECONDS": self.settings.query_timeout_seconds,
            },
        }
        if self.settings.role:
            kwargs["role"] = self.settings.role
        return kwargs


class WarehouseDatasetAdapter:
    """DatasetQueryAdapter-compatible wrapper around a warehouse connector."""

    def __init__(
        self,
        connector: WarehouseConnector,
        reference: WarehouseDatasetReference,
        row_limit: int = 10_000,
    ) -> None:
        self.connector = connector
        self.reference = reference
        self.row_limit = row_limit
        self._rows: list[dict[str, str]] | None = None
        self._columns: list[str] | None = None

    def columns(self) -> list[str]:
        if self._columns is None:
            described = self.connector.describe(self.reference)
            column_names = [column.name for column in described]
            if not column_names:
                preview = self.preview(limit=1)
                column_names = list(preview[0]) if preview else []
            self._columns = column_names
        return list(self._columns)

    def preview(self, limit: int = 5) -> list[dict[str, str]]:
        rows = self.connector.preview_rows(self.reference, limit=max(limit, 0))
        return [_stringify_row(row) for row in rows]

    def rows(self) -> list[dict[str, str]]:
        if self._rows is None:
            rows = self.connector.fetch_rows(self.reference, limit=max(self.row_limit, 0))
            self._rows = [_stringify_row(row) for row in rows]
        return [dict(row) for row in self._rows]

    def aggregate_sum_by(self, group_column: str, value_column: str) -> dict[str, float]:
        return self.connector.aggregate_sum_by(self.reference, group_column, value_column)


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
    credential_profile_id = _metadata_value(
        metadata,
        "credential_profile_id",
        "credential_profile",
        "connector_profile",
    )

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
        credential_profile_id=credential_profile_id or _default_credential_profile(source),
        metadata=metadata,
        parameters=_metadata_parameters(metadata),
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


def _metadata_parameters(metadata: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("parameters", "query_parameters", "warehouse_parameters"):
        value = metadata.get(key)
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise WarehouseConnectorError(f"Warehouse metadata {key} must be a mapping.")
        return dict(value)
    return {}


def _default_credential_profile(source: str) -> str | None:
    if source == "snowflake":
        return "snowflake-default"
    if source == "sqlite":
        return "local-filesystem"
    return None


def _normalize_source(source: str) -> str:
    return source.strip().lower().replace("-", "_")


def _quote_sqlite_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _row_total(row: Mapping[str, Any]) -> float:
    value = row.get("TOTAL") if "TOTAL" in row else row.get("total")
    return float(value or 0.0)


def _stringify_row(row: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): "" if value is None else str(value).strip() for key, value in row.items()}


def _merge_parameters(
    base_parameters: Mapping[str, Any], extra_parameters: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(base_parameters)
    collisions = sorted(set(merged).intersection(extra_parameters))
    if collisions:
        raise WarehouseConnectorError(
            "Warehouse query parameter cannot be reused: " + ", ".join(collisions)
        )
    merged.update(extra_parameters)
    return merged


def _parameter_count(parameters: ParameterSet) -> int:
    if parameters is None:
        return 0
    return len(parameters)


def _select_query(query: str | None) -> str:
    if not query or not query.strip():
        raise WarehouseConnectorError("Warehouse dataset query cannot be empty.")
    normalized = query.strip().lower()
    if not _starts_with_sql_keyword(normalized, "select", "with") or ";" in normalized:
        raise WarehouseConnectorError(
            "Warehouse dataset query must be a single SELECT or WITH statement."
        )
    return query.strip()


def _snowflake_statement(query: str) -> str:
    if not query or not query.strip():
        raise WarehouseConnectorError("Snowflake query cannot be empty.")
    statement = query.strip()
    normalized = statement.lower()
    if ";" in normalized or not _starts_with_sql_keyword(
        normalized, "select", "with", "show", "describe", "desc"
    ):
        raise WarehouseConnectorError(
            "Snowflake query must be a single SELECT, WITH, SHOW, or DESCRIBE statement."
        )
    return statement


def _starts_with_sql_keyword(normalized: str, *keywords: str) -> bool:
    return any(re.match(rf"^{re.escape(keyword)}($|\s)", normalized) for keyword in keywords)


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


def _parse_positive_int(values: Mapping[str, str], key: str, default: int) -> int:
    raw_value = values.get(key, "")
    if not str(raw_value).strip():
        return default
    try:
        parsed = int(str(raw_value).strip())
    except ValueError as exc:
        raise WarehouseConfigurationError(f"{key} must be a positive integer.") from exc
    if parsed <= 0:
        raise WarehouseConfigurationError(f"{key} must be a positive integer.")
    return parsed


def _snowflake_identifier(value: str, env_key: str) -> str:
    try:
        return _sql_identifier(value, allow_dotted=False)
    except WarehouseConnectorError as exc:
        raise WarehouseConfigurationError(
            f"{env_key} must be a safe unquoted Snowflake identifier."
        ) from exc


def _sql_identifier(identifier: str, *, allow_dotted: bool = True) -> str:
    parts = identifier.split(".") if allow_dotted else [identifier]
    if not parts or any(not _IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise WarehouseConnectorError(f"Unsafe SQL identifier: {identifier}")
    return ".".join(parts)


def _close_resource(resource: Any) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        close()

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from aeai_os.connectors import ConnectorRegistry
from aeai_os.data.warehouse import (
    WarehouseConnectorError,
    default_warehouse_registry,
    warehouse_reference_from_metadata,
)

DataSourceType = Literal["local_file", "sqlite", "snowflake"]
ValidationStatus = Literal["ok", "invalid"]
ALLOWED_LOCAL_DATASET_EXTENSIONS = {".csv", ".tsv", ".json", ".parquet"}


@dataclass(frozen=True)
class DataSourceValidationResult:
    status: ValidationStatus
    message: str
    checked_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataSourceRecord:
    id: str
    name: str
    source_type: DataSourceType
    connector_id: str
    credential_profile_id: str | None
    dataset_uri: str
    owner: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    latest_validation: DataSourceValidationResult | None = None

    def dataset_metadata(self) -> dict[str, Any]:
        base_metadata = dict(self.metadata)
        source = "warehouse" if self.source_type in {"sqlite", "snowflake"} else "reference"
        dataset_format = self.source_type if self.source_type != "local_file" else _local_format(
            self.dataset_uri
        )
        return {
            **base_metadata,
            "source": source,
            "format": dataset_format,
            "data_source_id": self.id,
            "data_source_name": self.name,
            "data_source_type": self.source_type,
            "connector_id": self.connector_id,
            "credential_profile_id": self.credential_profile_id,
            "owner": self.owner,
        }


class DataSourceNotFoundError(KeyError):
    pass


class DataSourceAlreadyExistsError(ValueError):
    pass


class DataSourceValidationError(ValueError):
    def __init__(self, result: DataSourceValidationResult) -> None:
        super().__init__(result.message)
        self.result = result


class DataSourceRegistry:
    def __init__(
        self,
        *,
        connector_registry: ConnectorRegistry,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._connector_registry = connector_registry
        self._env = env
        self._sources: dict[str, DataSourceRecord] = {}
        self._lock = RLock()

    def register(
        self,
        *,
        data_source_id: str,
        name: str,
        source_type: DataSourceType,
        dataset_uri: str,
        owner: str,
        connector_id: str | None = None,
        credential_profile_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DataSourceRecord:
        normalized_id = _normalize_id(data_source_id)
        normalized_name = _normalize_required(name, "Data source name")
        normalized_owner = _normalize_required(owner, "Data source owner")
        normalized_uri = _normalize_required(dataset_uri, "Dataset URI")
        normalized_metadata = dict(metadata or {})
        resolved_connector_id = connector_id or _default_connector_id(source_type)
        resolved_profile_id = credential_profile_id or _default_credential_profile_id(
            source_type
        )
        with self._lock:
            if normalized_id in self._sources:
                raise DataSourceAlreadyExistsError(
                    f"Data source already exists: {normalized_id}"
                )
        now = _now()
        record = DataSourceRecord(
            id=normalized_id,
            name=normalized_name,
            source_type=source_type,
            connector_id=resolved_connector_id,
            credential_profile_id=resolved_profile_id,
            dataset_uri=normalized_uri,
            owner=normalized_owner,
            metadata=normalized_metadata,
            created_at=now,
            updated_at=now,
        )
        validation = self.validate_record(record)
        if validation.status != "ok":
            raise DataSourceValidationError(validation)
        stored = replace(record, latest_validation=validation)
        with self._lock:
            self._sources[stored.id] = stored
            return stored

    def list_sources(self) -> list[DataSourceRecord]:
        with self._lock:
            return sorted(self._sources.values(), key=lambda source: source.created_at)

    def get(self, data_source_id: str) -> DataSourceRecord:
        with self._lock:
            try:
                return self._sources[data_source_id]
            except KeyError as exc:
                raise DataSourceNotFoundError(
                    f"Data source not found: {data_source_id}"
                ) from exc

    def validate(self, data_source_id: str) -> DataSourceValidationResult:
        with self._lock:
            source = self.get(data_source_id)
            validation = self.validate_record(source)
            self._sources[data_source_id] = replace(
                source,
                latest_validation=validation,
                updated_at=_now(),
            )
            return validation

    def validate_for_execution(self, data_source_id: str) -> DataSourceRecord:
        source = self.get(data_source_id)
        validation = self.validate_record(source)
        if validation.status != "ok":
            raise DataSourceValidationError(validation)
        with self._lock:
            updated = replace(source, latest_validation=validation, updated_at=_now())
            self._sources[data_source_id] = updated
            return updated

    def validate_record(
        self,
        source: DataSourceRecord,
    ) -> DataSourceValidationResult:
        if source.source_type == "local_file":
            return _validate_local_file_source(source)
        if source.source_type == "sqlite":
            return _validate_sqlite_source(source)
        if source.source_type == "snowflake":
            return self._validate_snowflake_source(source)
        return _invalid(
            f"Unsupported data source type: {source.source_type}.",
            {"source_type": source.source_type},
        )

    def _validate_snowflake_source(
        self,
        source: DataSourceRecord,
    ) -> DataSourceValidationResult:
        try:
            health = self._connector_registry.health(source.connector_id)
        except KeyError as exc:
            return _invalid(str(exc), {"connector_id": source.connector_id})
        if health.status != "ok":
            return _invalid(
                "Snowflake source is not configured. " + health.message,
                {"connector_id": source.connector_id, **health.details},
            )
        try:
            reference = warehouse_reference_from_metadata(
                source.dataset_uri,
                _warehouse_metadata(source),
            )
        except WarehouseConnectorError as exc:
            return _invalid(str(exc), {"connector_id": source.connector_id})
        relation = reference.qualified_table if reference.table else "query"
        return _ok(
            "Snowflake source configuration is valid.",
            {
                "connector_id": source.connector_id,
                "credential_profile_id": source.credential_profile_id,
                "relation": relation,
            },
        )


def _validate_local_file_source(source: DataSourceRecord) -> DataSourceValidationResult:
    path = Path(source.dataset_uri).expanduser()
    extension = path.suffix.lower()
    if extension not in ALLOWED_LOCAL_DATASET_EXTENSIONS:
        return _invalid(
            "Local dataset must be one of: csv, tsv, json, parquet.",
            {"dataset_uri": source.dataset_uri, "extension": extension},
        )
    if not path.exists():
        return _invalid(
            "Local dataset does not exist: "
            f"{path}. Upload or mount the file before registering it.",
            {"dataset_uri": source.dataset_uri},
        )
    if not path.is_file():
        return _invalid(
            f"Local dataset path is not a file: {path}.",
            {"dataset_uri": source.dataset_uri},
        )
    return _ok(
        "Local dataset is reachable.",
        {
            "dataset_uri": str(path),
            "format": _local_format(str(path)),
            "size_bytes": path.stat().st_size,
        },
    )


def _validate_sqlite_source(source: DataSourceRecord) -> DataSourceValidationResult:
    try:
        reference = warehouse_reference_from_metadata(
            source.dataset_uri,
            _warehouse_metadata(source),
        )
        connector = default_warehouse_registry().connector_for_reference(reference)
        columns = connector.describe(reference)
    except WarehouseConnectorError as exc:
        return _invalid(str(exc), {"connector_id": source.connector_id})
    return _ok(
        "SQLite source is reachable.",
        {
            "connector_id": source.connector_id,
            "credential_profile_id": source.credential_profile_id,
            "column_count": len(columns),
            "columns": [column.name for column in columns],
        },
    )


def _warehouse_metadata(source: DataSourceRecord) -> dict[str, Any]:
    warehouse_source = "snowflake" if source.source_type == "snowflake" else "sqlite"
    return {
        **source.metadata,
        "source": "warehouse",
        "warehouse_source": warehouse_source,
        "credential_profile_id": source.credential_profile_id,
    }


def _default_connector_id(source_type: DataSourceType) -> str:
    if source_type == "snowflake":
        return "snowflake-default"
    if source_type == "sqlite":
        return "sqlite-local"
    return "local-file"


def _default_credential_profile_id(source_type: DataSourceType) -> str:
    if source_type == "snowflake":
        return "snowflake-default"
    return "local-filesystem"


def _normalize_id(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "-").replace("_", "-")
    if len(normalized) < 3:
        raise ValueError("Data source ID must contain at least 3 characters.")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(character not in allowed for character in normalized):
        raise ValueError("Data source ID can only contain letters, numbers, and hyphens.")
    return normalized


def _normalize_required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required.")
    return normalized


def _local_format(uri: str) -> str:
    return Path(uri).suffix.lower().lstrip(".") or "file"


def _ok(message: str, details: dict[str, Any]) -> DataSourceValidationResult:
    return DataSourceValidationResult(
        status="ok",
        message=message,
        checked_at=_now(),
        details=details,
    )


def _invalid(message: str, details: dict[str, Any]) -> DataSourceValidationResult:
    return DataSourceValidationResult(
        status="invalid",
        message=message,
        checked_at=_now(),
        details=details,
    )


def _now() -> datetime:
    return datetime.now().astimezone()

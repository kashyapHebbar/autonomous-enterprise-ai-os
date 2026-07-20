from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from aeai_os.connectors.registry import (
    ConnectorHealth,
    ConnectorInstallation,
    ConnectorInstallationError,
    ConnectorRegistry,
)
from aeai_os.data.warehouse import (
    SnowflakeWarehouseConnector,
    SqliteWarehouseConnector,
    WarehouseColumn,
    WarehouseConnectorError,
    WarehouseDatasetReference,
)

AssetKind = Literal["folder", "file", "database", "schema", "table", "view", "object"]


@dataclass(frozen=True)
class ConnectorAsset:
    id: str
    name: str
    kind: AssetKind
    path: str
    can_browse: bool = False
    can_preview: bool = False
    can_select: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorBrowseResult:
    installation_id: str
    connector_id: str
    path: str
    assets: list[ConnectorAsset]


@dataclass(frozen=True)
class ConnectorPreview:
    installation_id: str
    connector_id: str
    asset_id: str
    asset_name: str
    columns: list[WarehouseColumn]
    rows: list[dict[str, Any]]
    truncated: bool


@dataclass(frozen=True)
class DatasetRegistrationSpec:
    source_type: Literal["local_file", "sqlite", "snowflake"]
    dataset_uri: str
    connector_id: str
    credential_profile_id: str | None
    metadata: dict[str, Any]


class ConnectorExplorer:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry

    def test(self, installation: ConnectorInstallation) -> ConnectorHealth:
        try:
            if installation.connector_id == "local-file":
                root = self._local_root(installation)
                if not root.is_dir():
                    raise ConnectorInstallationError(
                        f"Dataset root is not a readable directory: {root}."
                    )
                message = "Dataset directory is reachable."
                details = {"provider": "local", "kind": "file"}
            elif installation.connector_id == "sqlite-local":
                connector = self._sqlite_connector(installation)
                connector.execute_query("SELECT 1 AS connection_check")
                message = "SQLite database is reachable."
                details = {"provider": "sqlite", "kind": "warehouse"}
            elif installation.connector_id == "snowflake-default":
                connector = self._snowflake_connector(installation)
                connector.execute_query("SELECT CURRENT_VERSION() AS VERSION")
                message = "Snowflake connection succeeded."
                details = {"provider": "snowflake", "kind": "warehouse"}
            elif installation.connector_id == "artifact-store":
                client, bucket = self._object_client(installation)
                try:
                    client.head_bucket(Bucket=bucket)
                except Exception as exc:
                    raise ConnectorInstallationError(
                        "Object storage could not reach the configured bucket."
                    ) from exc
                message = "Object storage bucket is reachable."
                details = {"provider": "s3", "kind": "object_storage"}
            else:
                raise ConnectorInstallationError(
                    "Deep connection testing is not available for this connector yet."
                )
        except (OSError, WarehouseConnectorError, ConnectorInstallationError) as exc:
            return ConnectorHealth(
                connector_id=installation.connector_id,
                status="error",
                message=str(exc),
                checked_at=_now(),
                details={"probe": "live"},
            )
        return ConnectorHealth(
            connector_id=installation.connector_id,
            status="ok",
            message=message,
            checked_at=_now(),
            details={**details, "probe": "live"},
        )

    def browse(
        self, installation: ConnectorInstallation, path: str = ""
    ) -> ConnectorBrowseResult:
        normalized_path = path.strip().strip("/")
        if installation.connector_id == "local-file":
            assets = self._browse_local(installation, normalized_path)
        elif installation.connector_id == "sqlite-local":
            assets = self._browse_sqlite(installation, normalized_path)
        elif installation.connector_id == "snowflake-default":
            assets = self._browse_snowflake(installation, normalized_path)
        elif installation.connector_id == "artifact-store":
            assets = self._browse_objects(installation, normalized_path)
        else:
            raise ConnectorInstallationError(
                "Data browsing is available for local files, SQLite, and Snowflake installations."
            )
        return ConnectorBrowseResult(
            installation_id=installation.id,
            connector_id=installation.connector_id,
            path=normalized_path,
            assets=assets,
        )

    def preview(
        self,
        installation: ConnectorInstallation,
        asset_id: str,
        *,
        limit: int = 25,
    ) -> ConnectorPreview:
        bounded_limit = min(max(limit, 1), 100)
        if installation.connector_id == "local-file":
            path = self._local_asset(installation, asset_id)
            if path.suffix.lower() not in {".csv", ".tsv"}:
                raise ConnectorInstallationError(
                    "Preview currently supports CSV and TSV files."
                )
            delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                rows = [
                    dict(row)
                    for _, row in zip(range(bounded_limit + 1), reader, strict=False)
                ]
            names = list(rows[0]) if rows else list(reader.fieldnames or [])
            columns = [WarehouseColumn(name=name, data_type="unknown") for name in names]
        elif installation.connector_id == "sqlite-local":
            connector = self._sqlite_connector(installation)
            reference = self._sqlite_reference(installation, asset_id)
            columns = connector.describe(reference)
            rows = connector.preview_rows(reference, bounded_limit + 1)
        elif installation.connector_id == "snowflake-default":
            connector = self._snowflake_connector(installation)
            reference = self._snowflake_reference(installation, asset_id)
            columns = connector.describe(reference)
            rows = connector.preview_rows(reference, bounded_limit + 1)
        elif installation.connector_id == "artifact-store":
            columns, rows = self._preview_object(
                installation, asset_id, bounded_limit + 1
            )
        else:
            raise ConnectorInstallationError(
                "Dataset preview is not available for this connector."
            )
        return ConnectorPreview(
            installation_id=installation.id,
            connector_id=installation.connector_id,
            asset_id=asset_id,
            asset_name=asset_id.rsplit("/", 1)[-1],
            columns=columns,
            rows=rows[:bounded_limit],
            truncated=len(rows) > bounded_limit,
        )

    def registration_spec(
        self, installation: ConnectorInstallation, asset_id: str
    ) -> DatasetRegistrationSpec:
        connector = self._registry.get_connector(installation.connector_id)
        if installation.connector_id == "local-file":
            path = self._local_asset(installation, asset_id)
            return DatasetRegistrationSpec(
                source_type="local_file",
                dataset_uri=str(path),
                connector_id=connector.id,
                credential_profile_id=connector.credential_profile_id,
                metadata={"installation_id": installation.id, "asset_id": asset_id},
            )
        if installation.connector_id == "sqlite-local":
            reference = self._sqlite_reference(installation, asset_id)
            encoded_path = quote(str(Path(reference.database_path or "").resolve()), safe="/")
            return DatasetRegistrationSpec(
                source_type="sqlite",
                dataset_uri=f"sqlite://{encoded_path}#{quote(asset_id)}",
                connector_id=connector.id,
                credential_profile_id=connector.credential_profile_id,
                metadata={
                    "installation_id": installation.id,
                    "asset_id": asset_id,
                    "table": asset_id,
                    "database_path": reference.database_path,
                },
            )
        if installation.connector_id == "snowflake-default":
            reference = self._snowflake_reference(installation, asset_id)
            return DatasetRegistrationSpec(
                source_type="snowflake",
                dataset_uri=(
                    f"snowflake://{reference.database}/{reference.schema}/{reference.table}"
                ),
                connector_id=connector.id,
                credential_profile_id=connector.credential_profile_id,
                metadata={
                    "installation_id": installation.id,
                    "asset_id": asset_id,
                    "database": reference.database,
                    "schema": reference.schema,
                    "table": reference.table,
                },
            )
        raise ConnectorInstallationError(
            "This connector does not expose workflow-selectable datasets."
        )

    def warehouse_connector(
        self, installation: ConnectorInstallation
    ) -> SqliteWarehouseConnector | SnowflakeWarehouseConnector:
        if installation.connector_id == "sqlite-local":
            return self._sqlite_connector(installation)
        if installation.connector_id == "snowflake-default":
            return self._snowflake_connector(installation)
        raise ConnectorInstallationError(
            "The saved installation is not a warehouse connector."
        )

    def _browse_local(
        self, installation: ConnectorInstallation, path: str
    ) -> list[ConnectorAsset]:
        root = self._local_root(installation)
        directory = self._safe_child(root, path)
        if not directory.is_dir():
            raise ConnectorInstallationError(f"Dataset folder does not exist: {path or '/' }.")
        assets = []
        children = sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        for child in children:
            relative = child.relative_to(root).as_posix()
            if child.is_dir():
                assets.append(
                    ConnectorAsset(
                        id=relative,
                        name=child.name,
                        kind="folder",
                        path=relative,
                        can_browse=True,
                    )
                )
            elif child.suffix.lower() in {".csv", ".tsv", ".json", ".parquet"}:
                previewable = child.suffix.lower() in {".csv", ".tsv"}
                assets.append(
                    ConnectorAsset(
                        id=relative,
                        name=child.name,
                        kind="file",
                        path=relative,
                        can_preview=previewable,
                        can_select=True,
                        metadata={
                            "format": child.suffix.lower().lstrip("."),
                            "size_bytes": child.stat().st_size,
                        },
                    )
                )
        return assets

    def _browse_sqlite(
        self, installation: ConnectorInstallation, path: str
    ) -> list[ConnectorAsset]:
        if path:
            raise ConnectorInstallationError("SQLite tables are available at the database root.")
        rows = self._sqlite_connector(installation).execute_query(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).rows
        return [
            ConnectorAsset(
                id=str(row["name"]),
                name=str(row["name"]),
                kind="view" if row["type"] == "view" else "table",
                path=str(row["name"]),
                can_preview=True,
                can_select=True,
            )
            for row in rows
            if _SAFE_IDENTIFIER.fullmatch(str(row["name"]))
        ]

    def _browse_snowflake(
        self, installation: ConnectorInstallation, path: str
    ) -> list[ConnectorAsset]:
        configuration = installation.configuration
        database = configuration.get("database", "")
        schema = configuration.get("schema", "")
        if not path:
            return [ConnectorAsset(database, database, "database", database, can_browse=True)]
        if path == database:
            return [
                ConnectorAsset(
                    f"{database}/{schema}",
                    schema,
                    "schema",
                    f"{database}/{schema}",
                    can_browse=True,
                )
            ]
        if path != f"{database}/{schema}":
            raise ConnectorInstallationError(
                "The requested Snowflake catalog path is not permitted."
            )
        connector = self._snowflake_connector(installation)
        rows = connector.execute_query(f"SHOW TERSE TABLES IN SCHEMA {database}.{schema}").rows
        assets = []
        for row in rows:
            name = str(row.get("name") or row.get("NAME") or "")
            if _SAFE_IDENTIFIER.fullmatch(name):
                asset_id = f"{database}/{schema}/{name}"
                assets.append(
                    ConnectorAsset(
                        asset_id,
                        name,
                        "table",
                        asset_id,
                        can_preview=True,
                        can_select=True,
                    )
                )
        return assets

    def _browse_objects(
        self, installation: ConnectorInstallation, path: str
    ) -> list[ConnectorAsset]:
        client, bucket = self._object_client(installation)
        base_prefix = installation.configuration.get("prefix", "").strip("/")
        requested = path.strip("/")
        if requested and base_prefix and not (
            requested == base_prefix or requested.startswith(f"{base_prefix}/")
        ):
            raise ConnectorInstallationError(
                "The requested object path is outside the configured prefix."
            )
        current = requested or base_prefix
        prefix = f"{current}/" if current else ""
        try:
            response = client.list_objects_v2(
                Bucket=bucket,
                Prefix=prefix,
                Delimiter="/",
                MaxKeys=200,
            )
        except Exception as exc:
            raise ConnectorInstallationError(
                "Object catalog could not be listed. Verify bucket access and prefix permissions."
            ) from exc
        assets = [
            ConnectorAsset(
                id=str(item.get("Prefix") or "").strip("/"),
                name=str(item.get("Prefix") or "").strip("/").rsplit("/", 1)[-1],
                kind="folder",
                path=str(item.get("Prefix") or "").strip("/"),
                can_browse=True,
            )
            for item in response.get("CommonPrefixes", [])
            if item.get("Prefix")
        ]
        for item in response.get("Contents", []):
            key = str(item.get("Key") or "")
            if not key or key == prefix:
                continue
            previewable = Path(key).suffix.lower() in {".csv", ".tsv"}
            assets.append(
                ConnectorAsset(
                    id=key,
                    name=key.rsplit("/", 1)[-1],
                    kind="object",
                    path=key,
                    can_preview=previewable,
                    metadata={
                        "size_bytes": int(item.get("Size") or 0),
                        "format": Path(key).suffix.lower().lstrip("."),
                    },
                )
            )
        return assets

    def _preview_object(
        self,
        installation: ConnectorInstallation,
        asset_id: str,
        limit: int,
    ) -> tuple[list[WarehouseColumn], list[dict[str, Any]]]:
        key = asset_id.strip("/")
        base_prefix = installation.configuration.get("prefix", "").strip("/")
        if base_prefix and not key.startswith(f"{base_prefix}/"):
            raise ConnectorInstallationError(
                "The selected object is outside the configured prefix."
            )
        suffix = Path(key).suffix.lower()
        if suffix not in {".csv", ".tsv"}:
            raise ConnectorInstallationError(
                "Object preview currently supports CSV and TSV files."
            )
        client, bucket = self._object_client(installation)
        try:
            response = client.get_object(Bucket=bucket, Key=key, Range="bytes=0-1048575")
            body = response["Body"]
            payload = body.read() if hasattr(body, "read") else bytes(body)
        except Exception as exc:
            raise ConnectorInstallationError(
                "The selected object could not be read. Verify object permissions."
            ) from exc
        reader = csv.DictReader(
            io.StringIO(payload.decode("utf-8-sig")),
            delimiter="\t" if suffix == ".tsv" else ",",
        )
        rows = [dict(row) for _, row in zip(range(limit), reader, strict=False)]
        columns = [
            WarehouseColumn(name=name, data_type="unknown")
            for name in (reader.fieldnames or [])
        ]
        return columns, rows

    def _object_client(self, installation: ConnectorInstallation):
        try:
            import boto3
        except ImportError as exc:
            raise ConnectorInstallationError(
                "Object browsing requires the storage optional dependency."
            ) from exc
        configuration = installation.configuration
        bucket = configuration.get("bucket", "").strip()
        if not bucket:
            raise ConnectorInstallationError("Object storage requires a bucket.")
        effective_env = self._registry.resolve_installation_environment(installation)
        options: dict[str, Any] = {}
        endpoint = configuration.get("endpoint_url", "").strip()
        region = configuration.get("region", "").strip()
        access_key = effective_env.get("AWS_ACCESS_KEY_ID") or effective_env.get(
            "AEAI_ARTIFACT_S3_ACCESS_KEY_ID"
        )
        secret_key = effective_env.get("AWS_SECRET_ACCESS_KEY") or effective_env.get(
            "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY"
        )
        session_token = effective_env.get("AWS_SESSION_TOKEN")
        if endpoint:
            options["endpoint_url"] = endpoint
        if region:
            options["region_name"] = region
        if access_key:
            options["aws_access_key_id"] = access_key
        if secret_key:
            options["aws_secret_access_key"] = secret_key
        if session_token:
            options["aws_session_token"] = session_token
        return boto3.client("s3", **options), bucket

    def _local_root(self, installation: ConnectorInstallation) -> Path:
        value = installation.configuration.get("dataset_root", "").strip()
        if not value:
            raise ConnectorInstallationError(
                "Set a dataset root on this installation before browsing local files."
            )
        return Path(value).expanduser().resolve()

    def _local_asset(self, installation: ConnectorInstallation, asset_id: str) -> Path:
        path = self._safe_child(self._local_root(installation), asset_id)
        if not path.is_file():
            raise ConnectorInstallationError("Selected dataset file is not reachable.")
        return path

    @staticmethod
    def _safe_child(root: Path, relative: str) -> Path:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ConnectorInstallationError("Dataset path escapes the configured root.") from exc
        return candidate

    @staticmethod
    def _sqlite_connector(installation: ConnectorInstallation) -> SqliteWarehouseConnector:
        return SqliteWarehouseConnector(installation.configuration.get("database_path", ""))

    @staticmethod
    def _sqlite_reference(
        installation: ConnectorInstallation, asset_id: str
    ) -> WarehouseDatasetReference:
        if not _SAFE_IDENTIFIER.fullmatch(asset_id):
            raise ConnectorInstallationError("Selected SQLite table name is not supported.")
        return WarehouseDatasetReference(
            source="sqlite",
            table=asset_id,
            database_path=installation.configuration.get("database_path"),
        )

    def _snowflake_connector(
        self, installation: ConnectorInstallation
    ) -> SnowflakeWarehouseConnector:
        return SnowflakeWarehouseConnector.from_env(
            self._registry.resolve_installation_environment(installation)
        )

    @staticmethod
    def _snowflake_reference(
        installation: ConnectorInstallation, asset_id: str
    ) -> WarehouseDatasetReference:
        parts = asset_id.split("/")
        if len(parts) != 3 or any(not _SAFE_IDENTIFIER.fullmatch(part) for part in parts):
            raise ConnectorInstallationError("Select a valid Snowflake table from the catalog.")
        database, schema, table = parts
        allowed = installation.configuration
        if database != allowed.get("database") or schema != allowed.get("schema"):
            raise ConnectorInstallationError(
                "The selected Snowflake table is outside this installation."
            )
        return WarehouseDatasetReference(
            source="snowflake",
            database=database,
            schema=schema,
            table=table,
            credential_profile_id="snowflake-default",
        )


def _now():
    from datetime import datetime

    return datetime.now().astimezone()


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from aeai_os.settings import AppSettings

ConnectorStatus = Literal["ok", "not_configured"]


@dataclass(frozen=True)
class CredentialProfile:
    id: str
    provider: str
    credential_type: str
    env_keys: tuple[str, ...]
    secret_env_keys: tuple[str, ...] = ()
    alternative_env_groups: tuple[tuple[str, ...], ...] = ()
    description: str = ""

    def public_summary(self, env: Mapping[str, str]) -> dict[str, Any]:
        configured = tuple(key for key in self.env_keys if _has_env_value(env, key))
        missing = tuple(key for key in self.env_keys if not _has_env_value(env, key))
        missing_groups = [
            " or ".join(group)
            for group in self.alternative_env_groups
            if not any(_has_env_value(env, key) for key in group)
        ]
        return {
            "id": self.id,
            "provider": self.provider,
            "credential_type": self.credential_type,
            "description": self.description,
            "configured": not missing and not missing_groups,
            "configured_env_keys": list(configured),
            "missing_env_keys": [*missing, *missing_groups],
            "secret_env_keys": list(self.secret_env_keys),
        }


@dataclass(frozen=True)
class ConnectorHealth:
    connector_id: str
    status: ConnectorStatus
    message: str
    checked_at: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectorDefinition:
    id: str
    name: str
    provider: str
    kind: str
    credential_profile_id: str | None
    capabilities: tuple[str, ...]
    required_env_keys: tuple[str, ...] = ()
    optional_env_keys: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def health(self, env: Mapping[str, str]) -> ConnectorHealth:
        missing = [key for key in self.required_env_keys if not _has_env_value(env, key)]
        status: ConnectorStatus = "not_configured" if missing else "ok"
        message = (
            f"Missing required configuration: {', '.join(missing)}."
            if missing
            else "Connector profile is configured."
        )
        return ConnectorHealth(
            connector_id=self.id,
            status=status,
            message=message,
            checked_at=datetime.now().astimezone(),
            details={
                "provider": self.provider,
                "kind": self.kind,
                "credential_profile_id": self.credential_profile_id,
                "missing_env_keys": missing,
                "configured_env_keys": [
                    key for key in self.required_env_keys if _has_env_value(env, key)
                ],
            },
        )


class ConnectorRegistry:
    def __init__(
        self,
        connectors: list[ConnectorDefinition],
        credential_profiles: list[CredentialProfile],
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._connectors = {connector.id: connector for connector in connectors}
        self._credential_profiles = {
            profile.id: profile for profile in credential_profiles
        }
        self._env = os.environ if env is None else env

    def list_connectors(self) -> list[ConnectorDefinition]:
        return sorted(self._connectors.values(), key=lambda connector: connector.id)

    def get_connector(self, connector_id: str) -> ConnectorDefinition:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise KeyError(f"Connector not found: {connector_id}") from exc

    def list_credential_profiles(self) -> list[dict[str, Any]]:
        return [
            profile.public_summary(self._env)
            for profile in sorted(
                self._credential_profiles.values(),
                key=lambda profile: profile.id,
            )
        ]

    def health(self, connector_id: str) -> ConnectorHealth:
        return self.get_connector(connector_id).health(self._env)

    def connector_summary(self, connector: ConnectorDefinition) -> dict[str, Any]:
        health = connector.health(self._env)
        return {
            "id": connector.id,
            "name": connector.name,
            "provider": connector.provider,
            "kind": connector.kind,
            "credential_profile_id": connector.credential_profile_id,
            "capabilities": list(connector.capabilities),
            "status": health.status,
            "metadata": connector.metadata,
        }


def build_default_connector_registry(
    settings: AppSettings,
    env: Mapping[str, str] | None = None,
) -> ConnectorRegistry:
    values = os.environ if env is None else env
    artifact_backend = settings.artifact_storage_backend.strip().lower()
    artifact_profile = (
        "artifact-s3-default"
        if artifact_backend in {"s3", "minio", "object", "object_storage"}
        else "local-filesystem"
    )
    connectors = [
        ConnectorDefinition(
            id="sqlite-local",
            name="SQLite warehouse references",
            provider="sqlite",
            kind="warehouse",
            credential_profile_id="local-filesystem",
            capabilities=("preview", "describe", "query", "aggregate"),
            metadata={"configuration": "dataset_uri"},
        ),
        ConnectorDefinition(
            id="snowflake-default",
            name="Snowflake warehouse",
            provider="snowflake",
            kind="warehouse",
            credential_profile_id="snowflake-default",
            capabilities=("preview", "describe", "query", "aggregate"),
            required_env_keys=(
                "SNOWFLAKE_ACCOUNT",
                "SNOWFLAKE_USER",
                "SNOWFLAKE_PASSWORD",
                "SNOWFLAKE_WAREHOUSE",
                "SNOWFLAKE_DATABASE",
                "SNOWFLAKE_SCHEMA",
            ),
            optional_env_keys=(
                "SNOWFLAKE_ROLE",
                "SNOWFLAKE_CONNECT_TIMEOUT_SECONDS",
                "SNOWFLAKE_QUERY_TIMEOUT_SECONDS",
                "SNOWFLAKE_ROW_LIMIT",
                "SNOWFLAKE_APPLICATION",
            ),
        ),
        ConnectorDefinition(
            id="artifact-store",
            name="Artifact object storage",
            provider=artifact_backend or "local",
            kind="object_storage",
            credential_profile_id=artifact_profile,
            capabilities=("write_artifact", "read_artifact", "cache_artifact"),
            required_env_keys=_artifact_required_env_keys(artifact_backend),
            optional_env_keys=(
                "AEAI_ARTIFACT_S3_PREFIX",
                "AEAI_ARTIFACT_S3_ENDPOINT_URL",
                "AEAI_ARTIFACT_S3_REGION",
            ),
            metadata={"backend": artifact_backend or "local"},
        ),
        ConnectorDefinition(
            id="github-default",
            name="GitHub source control",
            provider="github",
            kind="source_control",
            credential_profile_id="github-default",
            capabilities=("repository_metadata", "issues", "pull_requests"),
            required_env_keys=_github_token_keys(values),
            metadata={"token_env_options": ["GITHUB_TOKEN", "GH_TOKEN"]},
        ),
    ]
    profiles = [
        CredentialProfile(
            id="local-filesystem",
            provider="local",
            credential_type="filesystem",
            env_keys=(),
            description="Local development profile for filesystem-backed datasets.",
        ),
        CredentialProfile(
            id="snowflake-default",
            provider="snowflake",
            credential_type="password",
            env_keys=(
                "SNOWFLAKE_ACCOUNT",
                "SNOWFLAKE_USER",
                "SNOWFLAKE_PASSWORD",
                "SNOWFLAKE_WAREHOUSE",
                "SNOWFLAKE_DATABASE",
                "SNOWFLAKE_SCHEMA",
            ),
            secret_env_keys=("SNOWFLAKE_PASSWORD",),
            description="Default Snowflake password profile from environment variables.",
        ),
        CredentialProfile(
            id="artifact-s3-default",
            provider="s3",
            credential_type="access_key",
            env_keys=(
                "AEAI_ARTIFACT_S3_BUCKET",
                "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
                "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
            ),
            secret_env_keys=("AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",),
            description="S3-compatible artifact storage profile.",
        ),
        CredentialProfile(
            id="github-default",
            provider="github",
            credential_type="token",
            env_keys=(),
            secret_env_keys=("GITHUB_TOKEN", "GH_TOKEN"),
            alternative_env_groups=(("GITHUB_TOKEN", "GH_TOKEN"),),
            description="GitHub token profile. Either token variable can satisfy the profile.",
        ),
    ]
    return ConnectorRegistry(connectors, profiles, env=values)


def _artifact_required_env_keys(backend: str) -> tuple[str, ...]:
    if backend in {"s3", "minio", "object", "object_storage"}:
        return (
            "AEAI_ARTIFACT_S3_BUCKET",
            "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
            "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
        )
    return ()


def _github_token_keys(env: Mapping[str, str]) -> tuple[str, ...]:
    if _has_env_value(env, "GITHUB_TOKEN") or _has_env_value(env, "GH_TOKEN"):
        return ()
    return ("GITHUB_TOKEN or GH_TOKEN",)


def _has_env_value(env: Mapping[str, str], key: str) -> bool:
    if " or " in key:
        return any(_has_env_value(env, part.strip()) for part in key.split(" or "))
    return bool(str(env.get(key, "")).strip())

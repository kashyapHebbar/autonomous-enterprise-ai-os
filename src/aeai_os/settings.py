from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    service_name: str = "autonomous-enterprise-ai-os"
    environment: str = "local"
    api_port: int = 8000
    artifact_root: str = "artifacts"
    artifact_storage_backend: str = "local"
    artifact_s3_bucket: str = ""
    artifact_s3_prefix: str = "aeai-artifacts"
    artifact_s3_endpoint_url: str = ""
    artifact_s3_region: str = ""
    artifact_s3_access_key_id: str = ""
    artifact_s3_secret_access_key: str = ""
    run_repository_backend: str = "memory"
    database_url: str = "postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os"
    workflow_queue_backend: str = "repository"
    workflow_execution_mode: str = "sync"
    procurement_workflow_max_attempts: int = 3
    workflow_queue_timeout_seconds: int = 300
    workflow_queue_key_prefix: str = "aeai:workflow"
    redis_url: str = "redis://redis:6379/0"
    auth_enabled: bool = False
    auth_mode: str = "local"
    auth_token_profiles: str = ""
    auth_local_user_id: str = "local-dev"
    auth_local_user_name: str = "Local Developer"
    auth_local_roles: str = "admin"
    auth_local_organization_id: str = "local-org"
    auth_local_workspace_ids: str = "default"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_roles_claim: str = "roles"
    oidc_organization_claim: str = "organization_id"
    oidc_workspaces_claim: str = "workspace_ids"
    run_repository_create_schema: bool = True
    secure_headers_enabled: bool = True
    max_request_body_bytes: int = 10 * 1024 * 1024
    hsts_max_age_seconds: int = 31_536_000


def get_settings() -> AppSettings:
    return AppSettings(
        service_name=os.getenv("AEAI_SERVICE_NAME", "autonomous-enterprise-ai-os"),
        environment=os.getenv("AEAI_ENV", "local"),
        api_port=int(os.getenv("AEAI_API_PORT", "8000")),
        artifact_root=os.getenv("AEAI_ARTIFACT_ROOT", "artifacts"),
        artifact_storage_backend=os.getenv("AEAI_ARTIFACT_STORAGE_BACKEND", "local"),
        artifact_s3_bucket=os.getenv(
            "AEAI_ARTIFACT_S3_BUCKET",
            os.getenv("MINIO_BUCKET", ""),
        ),
        artifact_s3_prefix=os.getenv("AEAI_ARTIFACT_S3_PREFIX", "aeai-artifacts"),
        artifact_s3_endpoint_url=os.getenv(
            "AEAI_ARTIFACT_S3_ENDPOINT_URL",
            os.getenv("MINIO_ENDPOINT", ""),
        ),
        artifact_s3_region=os.getenv("AEAI_ARTIFACT_S3_REGION", ""),
        artifact_s3_access_key_id=get_env_secret(
            "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
            "MINIO_ACCESS_KEY",
        ),
        artifact_s3_secret_access_key=get_env_secret(
            "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
            "MINIO_SECRET_KEY",
        ),
        run_repository_backend=os.getenv("AEAI_RUN_REPOSITORY_BACKEND", "memory"),
        run_repository_create_schema=_parse_bool(
            os.getenv("AEAI_RUN_REPOSITORY_CREATE_SCHEMA"),
            default=True,
        ),
        database_url=get_env_secret(
            "AEAI_DATABASE_URL",
            default="postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os",
        ),
        workflow_queue_backend=os.getenv("AEAI_WORKFLOW_QUEUE_BACKEND", "repository"),
        workflow_execution_mode=os.getenv("AEAI_WORKFLOW_EXECUTION_MODE", "sync"),
        procurement_workflow_max_attempts=int(
            os.getenv("AEAI_PROCUREMENT_WORKFLOW_MAX_ATTEMPTS", "3")
        ),
        workflow_queue_timeout_seconds=int(
            os.getenv("AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS", "300")
        ),
        workflow_queue_key_prefix=os.getenv(
            "AEAI_WORKFLOW_QUEUE_KEY_PREFIX",
            "aeai:workflow",
        ),
        redis_url=os.getenv("AEAI_REDIS_URL", "redis://redis:6379/0"),
        auth_enabled=_parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False),
        auth_mode=os.getenv("AEAI_AUTH_MODE", "").strip().lower()
        or ("token" if _parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False) else "local"),
        auth_token_profiles=get_env_secret("AEAI_AUTH_TOKEN_PROFILES"),
        auth_local_user_id=os.getenv("AEAI_AUTH_LOCAL_USER_ID", "local-dev"),
        auth_local_user_name=os.getenv("AEAI_AUTH_LOCAL_USER_NAME", "Local Developer"),
        auth_local_roles=os.getenv("AEAI_AUTH_LOCAL_ROLES", "admin"),
        auth_local_organization_id=os.getenv("AEAI_AUTH_LOCAL_ORGANIZATION_ID", "local-org"),
        auth_local_workspace_ids=os.getenv("AEAI_AUTH_LOCAL_WORKSPACE_IDS", "default"),
        oidc_issuer=os.getenv("AEAI_OIDC_ISSUER", ""),
        oidc_audience=os.getenv("AEAI_OIDC_AUDIENCE", ""),
        oidc_jwks_url=os.getenv("AEAI_OIDC_JWKS_URL", ""),
        oidc_roles_claim=os.getenv("AEAI_OIDC_ROLES_CLAIM", "roles"),
        oidc_organization_claim=os.getenv(
            "AEAI_OIDC_ORGANIZATION_CLAIM", "organization_id"
        ),
        oidc_workspaces_claim=os.getenv("AEAI_OIDC_WORKSPACES_CLAIM", "workspace_ids"),
        secure_headers_enabled=_parse_bool(
            os.getenv("AEAI_SECURE_HEADERS_ENABLED"),
            default=True,
        ),
        max_request_body_bytes=int(
            os.getenv("AEAI_MAX_REQUEST_BODY_BYTES", str(10 * 1024 * 1024))
        ),
        hsts_max_age_seconds=int(os.getenv("AEAI_HSTS_MAX_AGE_SECONDS", "31536000")),
    )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_secret(
    *names: str,
    default: str = "",
    env: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if env is None else env
    for name in names:
        direct = values.get(name)
        if direct is not None and direct.strip():
            return direct.strip()
    for name in names:
        file_path = values.get(f"{name}_FILE")
        if file_path is None or not file_path.strip():
            continue
        path = Path(file_path.strip()).expanduser()
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return default

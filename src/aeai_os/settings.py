from __future__ import annotations

import os
from dataclasses import dataclass


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
    workflow_queue_timeout_seconds: int = 300
    workflow_queue_key_prefix: str = "aeai:workflow"
    redis_url: str = "redis://redis:6379/0"
    auth_enabled: bool = False
    auth_local_user_id: str = "local-dev"
    auth_local_user_name: str = "Local Developer"
    auth_local_roles: str = "admin"


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
        artifact_s3_access_key_id=os.getenv(
            "AEAI_ARTIFACT_S3_ACCESS_KEY_ID",
            os.getenv("MINIO_ACCESS_KEY", ""),
        ),
        artifact_s3_secret_access_key=os.getenv(
            "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY",
            os.getenv("MINIO_SECRET_KEY", ""),
        ),
        run_repository_backend=os.getenv("AEAI_RUN_REPOSITORY_BACKEND", "memory"),
        database_url=os.getenv(
            "AEAI_DATABASE_URL",
            "postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os",
        ),
        workflow_queue_backend=os.getenv("AEAI_WORKFLOW_QUEUE_BACKEND", "repository"),
        workflow_queue_timeout_seconds=int(
            os.getenv("AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS", "300")
        ),
        workflow_queue_key_prefix=os.getenv(
            "AEAI_WORKFLOW_QUEUE_KEY_PREFIX",
            "aeai:workflow",
        ),
        redis_url=os.getenv("AEAI_REDIS_URL", "redis://redis:6379/0"),
        auth_enabled=_parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False),
        auth_local_user_id=os.getenv("AEAI_AUTH_LOCAL_USER_ID", "local-dev"),
        auth_local_user_name=os.getenv("AEAI_AUTH_LOCAL_USER_NAME", "Local Developer"),
        auth_local_roles=os.getenv("AEAI_AUTH_LOCAL_ROLES", "admin"),
    )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

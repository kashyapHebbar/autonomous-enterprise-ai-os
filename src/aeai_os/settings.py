from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    service_name: str = "autonomous-enterprise-ai-os"
    environment: str = "local"
    api_port: int = 8000
    artifact_root: str = "artifacts"
    run_repository_backend: str = "memory"
    database_url: str = "postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os"
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
        run_repository_backend=os.getenv("AEAI_RUN_REPOSITORY_BACKEND", "memory"),
        database_url=os.getenv(
            "AEAI_DATABASE_URL",
            "postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os",
        ),
        auth_enabled=_parse_bool(os.getenv("AEAI_AUTH_ENABLED"), default=False),
        auth_local_user_id=os.getenv("AEAI_AUTH_LOCAL_USER_ID", "local-dev"),
        auth_local_user_name=os.getenv("AEAI_AUTH_LOCAL_USER_NAME", "Local Developer"),
        auth_local_roles=os.getenv("AEAI_AUTH_LOCAL_ROLES", "admin"),
    )


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

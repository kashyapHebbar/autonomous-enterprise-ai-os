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
    workflow_queue_backend: str = "repository"
    workflow_queue_timeout_seconds: int = 300
    workflow_queue_key_prefix: str = "aeai:workflow"
    redis_url: str = "redis://redis:6379/0"


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
        workflow_queue_backend=os.getenv("AEAI_WORKFLOW_QUEUE_BACKEND", "repository"),
        workflow_queue_timeout_seconds=int(
            os.getenv("AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS", "300")
        ),
        workflow_queue_key_prefix=os.getenv(
            "AEAI_WORKFLOW_QUEUE_KEY_PREFIX",
            "aeai:workflow",
        ),
        redis_url=os.getenv("AEAI_REDIS_URL", "redis://redis:6379/0"),
    )

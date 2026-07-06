from __future__ import annotations

from aeai_os.settings import AppSettings, get_settings


def build_health_payload(settings: AppSettings | None = None) -> dict:
    settings = settings or get_settings()

    return {
        "service": settings.service_name,
        "environment": settings.environment,
        "status": "ok",
        "components": [
            {"name": "api", "status": "ok"},
            {"name": "orchestrator", "status": "not_configured"},
            {"name": "agent_registry", "status": "not_configured"},
            {
                "name": "artifact_store",
                "status": "ok",
                "backend": settings.artifact_storage_backend,
            },
            {
                "name": "run_repository",
                "status": "ok",
                "backend": settings.run_repository_backend,
                "create_schema": settings.run_repository_create_schema,
            },
        ],
    }

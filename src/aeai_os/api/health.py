from __future__ import annotations

from aeai_os.observability.tracing import build_tracing_config, resolve_span_processor
from aeai_os.settings import AppSettings, get_settings


def build_health_payload(settings: AppSettings | None = None) -> dict:
    settings = settings or get_settings()
    tracing_config = build_tracing_config(service_name=settings.service_name)
    tracing_resolution = resolve_span_processor(tracing_config)

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
            {
                "name": "connector_registry",
                "status": "ok",
            },
            {
                "name": "data_source_registry",
                "status": "ok",
            },
            {
                "name": "tracing",
                "status": tracing_resolution.status,
                "exporter": tracing_config.exporter,
                "endpoint_configured": bool(tracing_config.otlp_endpoint),
                "message": tracing_resolution.message,
            },
        ],
    }

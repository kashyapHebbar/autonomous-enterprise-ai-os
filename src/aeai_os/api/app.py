from __future__ import annotations

from pathlib import Path

from aeai_os.api.health import build_health_payload
from aeai_os.runs.factory import build_run_repository
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import get_settings
from aeai_os.storage import build_artifact_store


def create_app(
    repository: InMemoryRunRepository | None = None,
    artifact_root: Path | None = None,
):
    """Create the FastAPI app.

    FastAPI is imported lazily so scaffold smoke checks can run before dependencies
    are installed.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import FileResponse, JSONResponse

    from aeai_os.agents.registry import build_default_registry
    from aeai_os.api.admin import build_admin_router
    from aeai_os.api.auth import build_auth_router
    from aeai_os.api.connectors import build_connectors_router
    from aeai_os.api.data_sources import build_data_sources_router
    from aeai_os.api.investigations import build_investigations_router
    from aeai_os.api.metrics import build_metrics_router
    from aeai_os.api.runs import build_runs_router
    from aeai_os.connectors import (
        build_connector_installation_repository,
        build_default_connector_registry,
        build_default_credential_provider_registry,
    )
    from aeai_os.data.sources import DataSourceRegistry
    from aeai_os.observability.tracing import configure_tracing, current_trace_id, start_span
    from aeai_os.security import default_tool_permission_registry
    from aeai_os.security.redaction import redact_value
    from aeai_os.workflows.queue import build_workflow_queue

    settings = get_settings()
    configure_tracing(service_name=settings.service_name)
    run_repository = repository or build_run_repository(settings)
    run_artifact_root = artifact_root or Path(settings.artifact_root)
    workflow_queue = build_workflow_queue(settings, run_repository)
    artifact_store = build_artifact_store(settings, artifact_root=run_artifact_root)
    connector_registry = build_default_connector_registry(
        settings,
        installation_store=build_connector_installation_repository(settings),
        credential_resolver=build_default_credential_provider_registry(),
    )
    data_source_registry = DataSourceRegistry(connector_registry=connector_registry)
    agent_registry = build_default_registry()
    policy_registry = default_tool_permission_registry()
    static_root = Path(__file__).resolve().parents[1] / "web" / "static"

    app = FastAPI(
        title="Autonomous Enterprise AI Operating System",
        version="0.1.0",
        description="Durable multi-agent workflow platform for enterprise analytics.",
    )
    app.state.run_repository = run_repository
    app.state.artifact_root = run_artifact_root
    app.state.workflow_queue = workflow_queue
    app.state.artifact_store = artifact_store
    app.state.connector_registry = connector_registry
    app.state.data_source_registry = data_source_registry
    app.state.agent_registry = agent_registry
    app.state.policy_registry = policy_registry

    @app.exception_handler(HTTPException)
    async def redacted_http_exception(request, exc):
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": jsonable_encoder(redact_value(exc.detail))},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def redacted_validation_exception(request, exc):
        del request
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(redact_value(exc.errors()))},
        )

    @app.middleware("http")
    async def trace_requests(request, call_next):
        with start_span(
            "http.request",
            {
                "http.method": request.method,
                "http.target": request.url.path,
            },
        ) as span:
            try:
                response = await call_next(request)
            except Exception as exc:
                span.record_exception(exc)
                span.set_attribute("error", True)
                raise

            span.set_attribute("http.status_code", response.status_code)
            if response.status_code >= 500:
                span.set_attribute("error", True)
            trace_id = current_trace_id()
            if trace_id:
                response.headers["x-trace-id"] = trace_id
            return response

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "autonomous-enterprise-ai-os",
            "control_plane": "/app",
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
            "connectors": "/connectors",
            "data_sources": "/data-sources",
            "investigations": "/investigations",
            "artifact_browser": "/app/artifacts",
            "admin": "/app/admin",
            "run_inspector": "/run-inspector",
        }

    @app.get("/health")
    def health() -> dict:
        return build_health_payload()

    app.include_router(
        build_runs_router(
            run_repository,
            run_artifact_root,
            artifact_store,
            workflow_queue,
            workflow_execution_mode=settings.workflow_execution_mode,
            procurement_workflow_max_attempts=settings.procurement_workflow_max_attempts,
            data_source_registry=data_source_registry,
            connector_registry=connector_registry,
        )
    )
    app.include_router(build_metrics_router(run_repository))
    app.include_router(build_auth_router())
    app.include_router(build_investigations_router(run_repository, artifact_store))
    app.include_router(build_connectors_router(connector_registry, data_source_registry))
    app.include_router(build_data_sources_router(data_source_registry))
    app.include_router(
        build_admin_router(
            agent_registry=agent_registry,
            policy_registry=policy_registry,
            run_repository=run_repository,
        )
    )

    @app.get("/app", include_in_schema=False)
    def control_plane_page() -> FileResponse:
        return FileResponse(static_root / "control-plane.html")

    @app.get("/app/artifacts", include_in_schema=False)
    def artifact_browser_page() -> FileResponse:
        return FileResponse(static_root / "artifact-browser.html")

    @app.get("/app/investigations", include_in_schema=False)
    def investigations_page() -> FileResponse:
        return FileResponse(static_root / "investigations.html")

    @app.get("/app/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(static_root / "admin.html")

    @app.get("/app/{asset_name}", include_in_schema=False)
    def control_plane_asset(asset_name: str) -> FileResponse:
        allowed_assets = {
            "app-shell.css",
            "admin.css",
            "admin.js",
            "artifact-browser.css",
            "artifact-browser.js",
            "control-plane.css",
            "control-plane.js",
            "investigations.css",
            "investigations.js",
        }
        if asset_name not in allowed_assets:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(static_root / asset_name)

    @app.get("/run-inspector/runs/{run_id}", include_in_schema=False)
    def run_inspector_page(run_id: str) -> FileResponse:
        return FileResponse(static_root / "run-inspector.html")

    @app.get("/run-inspector/{asset_name}", include_in_schema=False)
    def run_inspector_asset(asset_name: str) -> FileResponse:
        allowed_assets = {
            "run-inspector.css",
            "run-inspector.js",
        }
        if asset_name not in allowed_assets:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(static_root / asset_name)

    return app

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
    from aeai_os.api.monitoring import build_monitoring_router
    from aeai_os.api.operations import build_operations_router
    from aeai_os.api.performance import build_performance_router
    from aeai_os.api.runs import build_runs_router
    from aeai_os.api.scaling import build_scaling_router
    from aeai_os.connectors import (
        build_connector_installation_repository,
        build_default_connector_registry,
        build_default_credential_provider_registry,
    )
    from aeai_os.data.sources import DataSourceRegistry
    from aeai_os.monitoring.store import MonitorStore
    from aeai_os.observability.tracing import configure_tracing, current_trace_id, start_span
    from aeai_os.security import default_tool_permission_registry
    from aeai_os.security.redaction import redact_value
    from aeai_os.workflows.queue import build_workflow_queue

    settings = get_settings()
    if settings.auth_mode not in {"local", "token", "oidc"}:
        raise ValueError("Unsupported authentication mode")
    if settings.environment.lower() in {"production", "prod", "staging"}:
        if settings.auth_mode == "local":
            raise ValueError("Production requires token or OIDC authentication")
        if settings.auth_mode == "token" and not settings.auth_token_profiles:
            raise ValueError("Production token authentication requires configured profiles")
        if settings.auth_mode == "oidc" and not (settings.oidc_issuer and settings.oidc_audience):
            raise ValueError("Production OIDC requires issuer and audience")
        if not settings.secure_headers_enabled:
            raise ValueError("Production requires secure HTTP headers")
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
    monitoring_store = MonitorStore(
        __import__("os").getenv("AEAI_MONITOR_DB_PATH", "artifacts/aeai-monitoring.db")
    )
    app.state.monitoring_store = monitoring_store
    app.state.run_repository = run_repository
    app.state.artifact_root = run_artifact_root
    app.state.workflow_queue = workflow_queue
    app.state.artifact_store = artifact_store
    app.state.connector_registry = connector_registry
    app.state.data_source_registry = data_source_registry
    app.state.agent_registry = agent_registry
    app.state.policy_registry = policy_registry

    class RequestBodyLimitMiddleware:
        def __init__(self, wrapped_app, max_body_bytes: int):
            self.app = wrapped_app
            self.max_body_bytes = max_body_bytes

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            received_bytes = 0
            response_started = False

            async def limited_receive():
                nonlocal received_bytes
                message = await receive()
                if message["type"] == "http.request":
                    received_bytes += len(message.get("body", b""))
                    if received_bytes > self.max_body_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail="Request body exceeds the configured limit.",
                        )
                return message

            async def tracked_send(message):
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                await send(message)

            try:
                await self.app(scope, limited_receive, tracked_send)
            except HTTPException as exc:
                if exc.status_code != 413 or response_started:
                    raise
                response = JSONResponse(status_code=413, content={"detail": exc.detail})
                await response(scope, receive, send)

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )

    @app.middleware("http")
    async def harden_http(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
            if request_size > settings.max_request_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body exceeds the configured limit."},
                )

        response = await call_next(request)
        if settings.secure_headers_enabled:
            response.headers["x-content-type-options"] = "nosniff"
            response.headers["x-frame-options"] = "DENY"
            response.headers["referrer-policy"] = "no-referrer"
            response.headers["permissions-policy"] = (
                "camera=(), geolocation=(), microphone=(), payment=(), usb=()"
            )
            response.headers["content-security-policy"] = (
                "default-src 'self'; object-src 'none'; base-uri 'self'; "
                "frame-ancestors 'none'; form-action 'self'; "
                "script-src 'self' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "  # noqa: E501
                "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'"
            )
            forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
            if settings.environment.lower() in {"production", "prod"} or forwarded_proto == "https":
                response.headers["strict-transport-security"] = (
                    f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
                )
        return response

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
    app.include_router(build_operations_router(run_repository, settings))
    app.include_router(build_performance_router(run_repository))
    app.include_router(build_scaling_router(run_repository, artifact_store))
    app.include_router(build_monitoring_router(monitoring_store, data_source_registry))
    from aeai_os.api.ingestion import build_ingestion_router

    app.include_router(build_ingestion_router())
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

    legacy_pages = {
        "": "control-plane.html",
        "artifacts": "artifact-browser.html",
        "investigations": "investigations.html",
        "admin": "admin.html",
    }

    legacy_assets = {
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

    @app.get("/legacy-app", include_in_schema=False)
    @app.get("/legacy-app/{legacy_page:path}", include_in_schema=False)
    def legacy_frontend(legacy_page: str = "") -> FileResponse:
        name = legacy_pages.get(legacy_page.strip("/"))
        if name is None:
            raise HTTPException(status_code=404)
        return FileResponse(static_root / name)

    @app.get("/app", include_in_schema=False)
    @app.get("/app/{resource_path:path}", include_in_schema=False)
    def frontend_page(resource_path: str = "") -> FileResponse:
        # Preserve old assets required by the standalone run inspector.
        if resource_path in legacy_assets:
            return FileResponse(static_root / resource_path)

        # Resolve the React build relative to the project root.
        frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
        react_index = frontend_dist / "index.html"

        if react_index.is_file():
            if resource_path:
                asset = (frontend_dist / resource_path).resolve()

                if (
                    asset.is_relative_to(frontend_dist.resolve())
                    and asset.is_file()
                    and asset != react_index.resolve()
                ):
                    return FileResponse(asset)

                if resource_path.startswith("assets/") or "." in Path(resource_path).name:
                    raise HTTPException(
                        status_code=404,
                        detail="Frontend asset not found.",
                    )

            # React Router handles frontend navigation.
            return FileResponse(react_index)

        # Until React is built, preserve the original interface.
        legacy_name = legacy_pages.get(resource_path.strip("/"))

        if legacy_name is not None:
            return FileResponse(static_root / legacy_name)

        if "." in Path(resource_path).name:
            raise HTTPException(status_code=404)

        raise HTTPException(
            status_code=503,
            detail=("React UI not built. Run: cd frontend && npm install && npm run build"),
        )

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

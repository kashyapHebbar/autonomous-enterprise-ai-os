from __future__ import annotations

from pathlib import Path

from aeai_os.api.health import build_health_payload
from aeai_os.runs.factory import build_run_repository
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.settings import get_settings


def create_app(
    repository: InMemoryRunRepository | None = None,
    artifact_root: Path | None = None,
):
    """Create the FastAPI app.

    FastAPI is imported lazily so scaffold smoke checks can run before dependencies
    are installed.
    """
    from fastapi import FastAPI

    from aeai_os.api.metrics import build_metrics_router
    from aeai_os.api.runs import build_runs_router
    from aeai_os.observability.tracing import configure_tracing, current_trace_id, start_span

    configure_tracing()
    settings = get_settings()
    run_repository = repository or build_run_repository(settings)
    run_artifact_root = artifact_root or Path(settings.artifact_root)

    app = FastAPI(
        title="Autonomous Enterprise AI Operating System",
        version="0.1.0",
        description="Durable multi-agent workflow platform for enterprise analytics.",
    )
    app.state.run_repository = run_repository
    app.state.artifact_root = run_artifact_root

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
            "docs": "/docs",
            "health": "/health",
            "metrics": "/metrics",
        }

    @app.get("/health")
    def health() -> dict:
        return build_health_payload()

    app.include_router(build_runs_router(run_repository, run_artifact_root))
    app.include_router(build_metrics_router(run_repository))

    return app

from __future__ import annotations

from pathlib import Path

from aeai_os.api.health import build_health_payload
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

    from aeai_os.api.runs import build_runs_router

    settings = get_settings()
    run_repository = repository or InMemoryRunRepository()
    run_artifact_root = artifact_root or Path(settings.artifact_root)

    app = FastAPI(
        title="Autonomous Enterprise AI Operating System",
        version="0.1.0",
        description="Durable multi-agent workflow platform for enterprise analytics.",
    )
    app.state.run_repository = run_repository
    app.state.artifact_root = run_artifact_root

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "autonomous-enterprise-ai-os",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health")
    def health() -> dict:
        return build_health_payload()

    app.include_router(build_runs_router(run_repository, run_artifact_root))

    return app

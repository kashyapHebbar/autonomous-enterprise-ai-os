from __future__ import annotations

from aeai_os.api.health import build_health_payload


def create_app():
    """Create the FastAPI app.

    FastAPI is imported lazily so scaffold smoke checks can run before dependencies
    are installed.
    """
    from fastapi import FastAPI

    app = FastAPI(
        title="Autonomous Enterprise AI Operating System",
        version="0.1.0",
        description="Durable multi-agent workflow platform for enterprise analytics.",
    )

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

    return app


from __future__ import annotations

from fastapi import APIRouter, Response

from aeai_os.observability.metrics import render_prometheus_metrics
from aeai_os.runs.repository import InMemoryRunRepository

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def build_metrics_router(repository: InMemoryRunRepository) -> APIRouter:
    router = APIRouter(tags=["observability"])

    @router.get("/metrics", response_class=Response)
    def metrics() -> Response:
        return Response(
            content=render_prometheus_metrics(repository),
            media_type=PROMETHEUS_CONTENT_TYPE,
        )

    return router

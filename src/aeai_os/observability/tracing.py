from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

_CONFIGURED = False
_TRACER_NAME = "aeai_os"


def configure_tracing(service_name: str = "autonomous-enterprise-ai-os") -> None:
    """Install an SDK tracer provider so local spans get real trace IDs."""

    global _CONFIGURED
    if _CONFIGURED:
        return

    provider = trace.get_tracer_provider()
    if provider.__class__.__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(
            TracerProvider(
                resource=Resource.create(
                    {
                        "service.name": service_name,
                        "service.namespace": "autonomous-enterprise-ai-os",
                    }
                )
            )
        )
    _CONFIGURED = True


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid and span_context.trace_id:
        return f"{span_context.trace_id:032x}"
    return None


def ensure_trace_id(trace_id: str | None = None) -> str:
    normalized = (trace_id or "").strip()
    if normalized:
        return normalized
    return current_trace_id() or uuid4().hex


@contextmanager
def start_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[trace.Span]:
    configure_tracing()
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(
        name,
        attributes=_normalize_attributes(attributes or {}),
    ) as span:
        yield span


def _normalize_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, str | bool | int | float):
            normalized[key] = value
        elif isinstance(value, list | tuple) and all(
            isinstance(item, str | bool | int | float) for item in value
        ):
            normalized[key] = list(value)
        else:
            normalized[key] = str(value)
    return normalized

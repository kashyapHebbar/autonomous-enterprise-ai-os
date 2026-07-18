from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

_CONFIGURED = False
_CONFIGURED_RESULT: TracingConfigurationResult | None = None
_TRACER_NAME = "aeai_os"
_CURRENT_TRACE_ID: ContextVar[str | None] = ContextVar("aeai_trace_id", default=None)
_CURRENT_CORRELATION_ATTRIBUTES: ContextVar[dict[str, Any] | None] = ContextVar(
    "aeai_trace_correlation_attributes",
    default=None,
)


@dataclass(frozen=True)
class TracingConfig:
    service_name: str = "autonomous-enterprise-ai-os"
    service_namespace: str = "autonomous-enterprise-ai-os"
    exporter: str = "none"
    otlp_endpoint: str | None = None
    otlp_headers: dict[str, str] = field(default_factory=dict)
    otlp_insecure: bool = False

    @property
    def enabled(self) -> bool:
        return self.exporter != "disabled"


@dataclass(frozen=True)
class TracingExporterResolution:
    processor: Any | None
    status: str
    message: str | None = None


@dataclass(frozen=True)
class TracingConfigurationResult:
    config: TracingConfig
    configured: bool
    exporter_status: str
    message: str | None = None


def build_tracing_config(
    service_name: str = "autonomous-enterprise-ai-os",
    env: Mapping[str, str] | None = None,
) -> TracingConfig:
    values = os.environ if env is None else env
    enabled = _parse_bool(values.get("AEAI_TRACING_ENABLED"), default=True)
    exporter = _normalize_exporter(values.get("AEAI_TRACE_EXPORTER", "none"))
    if not enabled:
        exporter = "disabled"

    return TracingConfig(
        service_name=service_name,
        exporter=exporter,
        otlp_endpoint=(
            values.get("AEAI_OTEL_EXPORTER_OTLP_ENDPOINT")
            or values.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or None
        ),
        otlp_headers=_parse_headers(
            values.get("AEAI_OTEL_EXPORTER_OTLP_HEADERS")
            or values.get("OTEL_EXPORTER_OTLP_HEADERS")
            or ""
        ),
        otlp_insecure=_parse_bool(
            values.get("AEAI_OTEL_EXPORTER_OTLP_INSECURE")
            or values.get("OTEL_EXPORTER_OTLP_INSECURE"),
            default=False,
        ),
    )


def resolve_span_processor(config: TracingConfig) -> TracingExporterResolution:
    if config.exporter in {"disabled", "none"}:
        return TracingExporterResolution(
            processor=None,
            status=("disabled" if config.exporter == "disabled" else "not_configured"),
        )

    if config.exporter == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

        return TracingExporterResolution(
            processor=SimpleSpanProcessor(ConsoleSpanExporter()),
            status="configured",
        )

    if config.exporter == "otlp_http":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            return TracingExporterResolution(
                processor=None,
                status="unavailable",
                message=(
                    "OTLP/HTTP tracing requested but opentelemetry-exporter-otlp-proto-http "
                    "is not installed."
                ),
            )
        exporter_kwargs = _otlp_exporter_kwargs(config, include_insecure=False)
        return TracingExporterResolution(
            processor=BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)),
            status="configured",
        )

    if config.exporter == "otlp_grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
        except ImportError:
            return TracingExporterResolution(
                processor=None,
                status="unavailable",
                message=(
                    "OTLP/gRPC tracing requested but opentelemetry-exporter-otlp-proto-grpc "
                    "is not installed."
                ),
            )
        exporter_kwargs = _otlp_exporter_kwargs(config, include_insecure=True)
        return TracingExporterResolution(
            processor=BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)),
            status="configured",
        )

    return TracingExporterResolution(
        processor=None,
        status="unavailable",
        message=f"Unsupported tracing exporter: {config.exporter}",
    )


def configure_tracing(
    service_name: str = "autonomous-enterprise-ai-os",
    env: Mapping[str, str] | None = None,
) -> TracingConfigurationResult:
    """Install an SDK tracer provider and optional exporter from environment config."""

    global _CONFIGURED, _CONFIGURED_RESULT
    if _CONFIGURED:
        return _CONFIGURED_RESULT or TracingConfigurationResult(
            config=build_tracing_config(service_name=service_name, env=env),
            configured=False,
            exporter_status="already_configured",
        )

    config = build_tracing_config(service_name=service_name, env=env)
    if not config.enabled:
        _CONFIGURED = True
        _CONFIGURED_RESULT = TracingConfigurationResult(
            config=config,
            configured=False,
            exporter_status="disabled",
        )
        return _CONFIGURED_RESULT

    if config.exporter == "none":
        _CONFIGURED = True
        _CONFIGURED_RESULT = TracingConfigurationResult(
            config=config,
            configured=False,
            exporter_status="not_configured",
        )
        return _CONFIGURED_RESULT

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = trace.get_tracer_provider()
    if provider.__class__.__name__ == "ProxyTracerProvider":
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": config.service_name,
                    "service.namespace": config.service_namespace,
                }
            )
        )
        trace.set_tracer_provider(provider)

    resolution = resolve_span_processor(config)
    if resolution.processor is not None and hasattr(provider, "add_span_processor"):
        provider.add_span_processor(resolution.processor)

    _CONFIGURED = True
    _CONFIGURED_RESULT = TracingConfigurationResult(
        config=config,
        configured=True,
        exporter_status=resolution.status,
        message=resolution.message,
    )
    return _CONFIGURED_RESULT


def current_trace_id() -> str | None:
    local_trace_id = _CURRENT_TRACE_ID.get()
    if local_trace_id:
        return local_trace_id
    if _CONFIGURED_RESULT is None or _CONFIGURED_RESULT.exporter_status in {
        "disabled",
        "not_configured",
    }:
        return None
    from opentelemetry import trace

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
def trace_context(attributes: Mapping[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    current = dict(_CURRENT_CORRELATION_ATTRIBUTES.get() or {})
    merged = {**current, **_normalize_attributes(attributes or {})}
    token = _CURRENT_CORRELATION_ATTRIBUTES.set(merged)
    try:
        yield merged
    finally:
        _CURRENT_CORRELATION_ATTRIBUTES.reset(token)


def current_correlation_attributes() -> dict[str, Any]:
    return dict(_CURRENT_CORRELATION_ATTRIBUTES.get() or {})


@contextmanager
def start_span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    configuration = configure_tracing()
    span_attributes = {
        **current_correlation_attributes(),
        **_normalize_attributes(attributes or {}),
    }
    if configuration.exporter_status in {"disabled", "not_configured"}:
        trace_id = current_trace_id() or uuid4().hex
        token = _CURRENT_TRACE_ID.set(trace_id)
        try:
            yield _NoopSpan(trace_id=trace_id, attributes=dict(span_attributes))
        finally:
            _CURRENT_TRACE_ID.reset(token)
        return

    from opentelemetry import trace

    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(
        name,
        attributes=span_attributes,
    ) as span:
        yield span


@dataclass
class _NoopSpan:
    trace_id: str
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def set_attribute(self, key: str, value: Any) -> None:
        normalized = _normalize_attributes({key: value})
        self.attributes.update(normalized)

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        self.events.append(
            {
                "name": name,
                "attributes": _normalize_attributes(attributes or {}),
            }
        )

    def record_exception(self, exception: BaseException) -> None:
        self.exceptions.append(f"{type(exception).__name__}: {exception}")


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


def _normalize_exporter(value: str | None) -> str:
    normalized = (value or "none").strip().lower().replace("-", "_")
    aliases = {
        "off": "disabled",
        "false": "disabled",
        "0": "disabled",
        "no": "disabled",
        "noop": "none",
        "otlp": "otlp_http",
        "otlphttp": "otlp_http",
        "otlp_http/protobuf": "otlp_http",
        "otlpgrpc": "otlp_grpc",
    }
    return aliases.get(normalized, normalized)


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_headers(value: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for item in value.split(","):
        if "=" not in item:
            continue
        key, raw_value = item.split("=", 1)
        normalized_key = key.strip()
        if normalized_key:
            headers[normalized_key] = raw_value.strip()
    return headers


def _otlp_exporter_kwargs(config: TracingConfig, *, include_insecure: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if config.otlp_endpoint:
        kwargs["endpoint"] = config.otlp_endpoint
    if config.otlp_headers:
        kwargs["headers"] = config.otlp_headers
    if include_insecure:
        kwargs["insecure"] = config.otlp_insecure
    return kwargs

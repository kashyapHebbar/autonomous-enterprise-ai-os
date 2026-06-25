from __future__ import annotations

from aeai_os.observability import (
    TracingConfig,
    build_tracing_config,
    resolve_span_processor,
)


def test_tracing_config_defaults_to_local_non_exporting_provider():
    config = build_tracing_config(service_name="aeai-test", env={})

    assert config.enabled is True
    assert config.service_name == "aeai-test"
    assert config.exporter == "none"
    assert config.otlp_endpoint is None
    assert resolve_span_processor(config).status == "not_configured"


def test_tracing_config_can_be_disabled_by_env():
    config = build_tracing_config(
        service_name="aeai-test",
        env={"AEAI_TRACING_ENABLED": "false", "AEAI_TRACE_EXPORTER": "console"},
    )
    resolution = resolve_span_processor(config)

    assert config.enabled is False
    assert config.exporter == "disabled"
    assert resolution.processor is None
    assert resolution.status == "disabled"


def test_console_trace_exporter_resolves_without_external_services():
    config = build_tracing_config(
        service_name="aeai-test",
        env={"AEAI_TRACE_EXPORTER": "console"},
    )
    resolution = resolve_span_processor(config)

    assert config.exporter == "console"
    assert resolution.processor is not None
    assert resolution.status == "configured"


def test_otlp_trace_exporter_config_fails_gracefully_when_optional_package_is_missing():
    config = build_tracing_config(
        service_name="aeai-test",
        env={
            "AEAI_TRACE_EXPORTER": "otlp_http",
            "AEAI_OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/v1/traces",
            "AEAI_OTEL_EXPORTER_OTLP_HEADERS": "authorization=Bearer test,team=platform",
        },
    )
    resolution = resolve_span_processor(config)

    assert config.exporter == "otlp_http"
    assert config.otlp_endpoint == "http://collector:4318/v1/traces"
    assert config.otlp_headers == {"authorization": "Bearer test", "team": "platform"}
    assert resolution.status in {"configured", "unavailable"}
    if resolution.status == "unavailable":
        assert "opentelemetry-exporter-otlp-proto-http" in resolution.message


def test_unsupported_trace_exporter_reports_unavailable():
    resolution = resolve_span_processor(
        TracingConfig(service_name="aeai-test", exporter="custom_sink")
    )

    assert resolution.processor is None
    assert resolution.status == "unavailable"
    assert "custom_sink" in resolution.message

from __future__ import annotations

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.observability import (
    TracingConfig,
    build_tracing_config,
    current_correlation_attributes,
    current_trace_id,
    resolve_span_processor,
    start_span,
    trace_context,
)


def _write_procurement_dataset(path):
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-05,100,IT",
                "Zenith,Hardware,2026-02-01,200,Operations",
            ]
        ),
        encoding="utf-8",
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


def test_noop_nested_spans_share_local_trace_id():
    with start_span("outer") as outer:
        outer_trace_id = current_trace_id()
        with start_span("inner") as inner:
            inner_trace_id = current_trace_id()

    assert outer_trace_id == outer.trace_id
    assert inner_trace_id == outer_trace_id
    assert inner.trace_id == outer_trace_id


def test_trace_context_applies_correlation_attributes_to_noop_span():
    with trace_context({"run.id": "run_123", "graph.node.id": "data_profile"}):
        with start_span("agent.node", {"agent.type": "data_retrieval"}) as span:
            attributes = current_correlation_attributes()

    assert attributes == {"run.id": "run_123", "graph.node.id": "data_profile"}
    assert span.attributes["run.id"] == "run_123"
    assert span.attributes["graph.node.id"] == "data_profile"
    assert span.attributes["agent.type"] == "data_retrieval"


def test_api_run_events_correlate_run_and_request_trace_ids(tmp_path):
    dataset_path = tmp_path / "procurement.csv"
    _write_procurement_dataset(dataset_path)
    client = TestClient(create_app(artifact_root=tmp_path / "artifacts"))

    create_response = client.post(
        "/runs",
        json={
            "task": "Analyze procurement spend and create a dashboard report.",
            "dataset_uri": str(dataset_path),
        },
    )
    run = create_response.json()
    execute_response = client.post(f"/runs/{run['id']}/execute/procurement")
    events_response = client.get(f"/runs/{run['id']}/events")

    events = events_response.json()
    correlated_events = [
        event
        for event in events
        if event["payload"].get("otel_trace_id") == execute_response.headers["x-trace-id"]
    ]
    assert create_response.status_code == 201
    assert execute_response.status_code == 200
    assert events_response.status_code == 200
    assert run["trace_id"] == create_response.headers["x-trace-id"]
    assert execute_response.json()["trace_id"] == run["trace_id"]
    assert all(
        event["payload"].get("trace_id") == run["trace_id"]
        for event in events
        if "trace_id" in event["payload"]
    )
    assert correlated_events

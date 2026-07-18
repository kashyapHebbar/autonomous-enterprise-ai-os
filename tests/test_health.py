from aeai_os.api.health import build_health_payload


def test_health_payload_has_expected_shape():
    payload = build_health_payload()

    assert payload["service"] == "autonomous-enterprise-ai-os"
    assert payload["environment"] == "local"
    assert payload["status"] == "ok"

    component_names = {component["name"] for component in payload["components"]}
    assert {
        "api",
        "orchestrator",
        "agent_registry",
        "connector_registry",
        "data_source_registry",
        "artifact_store",
        "run_repository",
        "tracing",
    } <= component_names

    run_repository = next(
        component
        for component in payload["components"]
        if component["name"] == "run_repository"
    )
    assert run_repository["backend"] == "memory"
    assert run_repository["create_schema"] is True

    tracing = next(
        component
        for component in payload["components"]
        if component["name"] == "tracing"
    )
    assert tracing["exporter"] == "none"
    assert tracing["status"] == "not_configured"

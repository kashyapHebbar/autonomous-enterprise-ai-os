from aeai_os.api.health import build_health_payload


def test_health_payload_has_expected_shape():
    payload = build_health_payload()

    assert payload["service"] == "autonomous-enterprise-ai-os"
    assert payload["environment"] == "local"
    assert payload["status"] == "ok"

    component_names = {component["name"] for component in payload["components"]}
    assert {"api", "orchestrator", "agent_registry", "artifact_store"} <= component_names


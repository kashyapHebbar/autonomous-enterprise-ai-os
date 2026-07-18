from fastapi.testclient import TestClient

from aeai_os.api.app import create_app


def test_connectors_api_lists_connectors_profiles_and_health(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct")
    monkeypatch.setenv("SNOWFLAKE_USER", "user")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "secret-password")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "ANALYTICS")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    client = TestClient(create_app())

    connectors_response = client.get("/connectors")
    profiles_response = client.get("/connectors/credential-profiles")
    health_response = client.get("/connectors/snowflake-default/health")
    missing_response = client.get("/connectors/missing/health")

    connectors = connectors_response.json()
    profiles = profiles_response.json()
    assert connectors_response.status_code == 200
    assert profiles_response.status_code == 200
    assert health_response.status_code == 200
    assert missing_response.status_code == 404
    assert any(connector["id"] == "snowflake-default" for connector in connectors)
    assert health_response.json()["status"] == "ok"
    assert "secret-password" not in str(profiles)
    assert any(profile["id"] == "snowflake-default" for profile in profiles)

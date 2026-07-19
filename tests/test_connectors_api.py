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


def test_connector_installation_api_creates_lists_and_tests_tenant_scoped_installation(
    monkeypatch,
):
    for key, value in {
        "SNOWFLAKE_ACCOUNT": "acct",
        "SNOWFLAKE_USER": "user",
        "SNOWFLAKE_PASSWORD": "secret-password",
        "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
        "SNOWFLAKE_DATABASE": "ANALYTICS",
        "SNOWFLAKE_SCHEMA": "PUBLIC",
    }.items():
        monkeypatch.setenv(key, value)
    client = TestClient(create_app())

    response = client.post(
        "/connectors/installations",
        json={
            "connector_id": "snowflake-default",
            "name": "Finance Snowflake",
            "credential_reference": "env://SNOWFLAKE_USER/SNOWFLAKE_PASSWORD",
            "configuration": {
                "account": "acct",
                "warehouse": "COMPUTE_WH",
                "database": "ANALYTICS",
                "schema": "PUBLIC",
            },
        },
    )

    installation = response.json()
    own_list = client.get("/connectors/installations")
    test_response = client.post(
        f"/connectors/installations/{installation['id']}/test"
    )

    assert response.status_code == 201
    assert installation["status"] == "ready"
    assert installation["credential_reference"] == "env://SNOWFLAKE_USER/SNOWFLAKE_PASSWORD"
    assert "secret-password" not in str(installation)
    assert own_list.json() == [installation]
    assert installation["organization_id"] == "local-org"
    assert installation["workspace_id"] == "default"
    assert test_response.status_code == 200
    assert test_response.json()["status"] == "ok"


def test_connector_installation_api_rejects_raw_secret_configuration():
    client = TestClient(create_app())

    response = client.post(
        "/connectors/installations",
        json={
            "connector_id": "snowflake-default",
            "name": "Unsafe Snowflake",
            "credential_reference": "vault://acme/snowflake",
            "configuration": {"password": "must-not-be-stored"},
        },
    )

    assert response.status_code == 422
    assert "password" in response.json()["detail"]
    assert "must-not-be-stored" not in response.text

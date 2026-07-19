import pytest

from aeai_os.connectors import ConnectorInstallationError, build_default_connector_registry
from aeai_os.settings import AppSettings


def test_connector_registry_lists_sanitized_profiles_and_health():
    env = {
        "SNOWFLAKE_ACCOUNT": "acct",
        "SNOWFLAKE_USER": "user",
        "SNOWFLAKE_PASSWORD": "super-secret",
        "SNOWFLAKE_WAREHOUSE": "COMPUTE_WH",
        "SNOWFLAKE_DATABASE": "ANALYTICS",
        "SNOWFLAKE_SCHEMA": "PUBLIC",
        "GITHUB_TOKEN": "ghp_secret",
    }
    registry = build_default_connector_registry(AppSettings(), env=env)

    connectors = {connector.id: connector for connector in registry.list_connectors()}
    profiles = registry.list_credential_profiles()
    snowflake_health = registry.health("snowflake-default")
    github_health = registry.health("github-default")

    rendered_profiles = str(profiles)
    assert {"sqlite-local", "snowflake-default", "artifact-store", "github-default"} <= set(
        connectors
    )
    assert snowflake_health.status == "ok"
    assert github_health.status == "ok"
    assert "super-secret" not in rendered_profiles
    assert "ghp_secret" not in rendered_profiles
    assert any(profile["id"] == "snowflake-default" for profile in profiles)


def test_connector_registry_reports_missing_configuration_without_secret_values():
    registry = build_default_connector_registry(
        AppSettings(artifact_storage_backend="s3"),
        env={},
    )

    snowflake_health = registry.health("snowflake-default")
    artifact_health = registry.health("artifact-store")
    github_profile = next(
        profile
        for profile in registry.list_credential_profiles()
        if profile["id"] == "github-default"
    )

    assert snowflake_health.status == "not_configured"
    assert "SNOWFLAKE_PASSWORD" in snowflake_health.details["missing_env_keys"]
    assert artifact_health.status == "not_configured"
    assert "AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY" in artifact_health.details["missing_env_keys"]
    assert github_profile["configured"] is False
    assert github_profile["missing_env_keys"] == ["GITHUB_TOKEN or GH_TOKEN"]


def test_connector_installations_are_tenant_scoped_and_secret_safe():
    registry = build_default_connector_registry(AppSettings(), env={})
    installation = registry.create_installation(
        connector_id="snowflake-default",
        name="Finance warehouse",
        organization_id="acme",
        workspace_id="finance",
        credential_reference="aws-secrets://acme/snowflake-finance",
        configuration={
            "account": "acme.eu-west-1",
            "warehouse": "COMPUTE_WH",
            "database": "ANALYTICS",
            "schema": "PUBLIC",
        },
        created_by="admin-1",
    )

    assert installation.status == "setup_required"
    assert registry.list_installations("acme") == [installation]
    assert registry.list_installations("another-org") == []

    with pytest.raises(ConnectorInstallationError, match="Unknown connector configuration"):
        registry.create_installation(
            connector_id="snowflake-default",
            name="Unsafe warehouse",
            organization_id="acme",
            workspace_id=None,
            credential_reference="aws-secrets://acme/snowflake",
            configuration={"password": "must-not-be-stored"},
            created_by="admin-1",
        )

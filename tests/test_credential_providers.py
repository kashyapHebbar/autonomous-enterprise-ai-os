import json
from types import SimpleNamespace

import pytest

from aeai_os.connectors import (
    AWSSecretsManagerCredentialProvider,
    AzureKeyVaultCredentialProvider,
    CredentialProviderRegistry,
    CredentialResolutionError,
    EnvironmentCredentialProvider,
    VaultCredentialProvider,
)


def test_environment_provider_resolves_only_named_keys():
    provider = EnvironmentCredentialProvider(
        {"SNOWFLAKE_USER": "analyst", "SNOWFLAKE_PASSWORD": "secret", "OTHER": "hidden"}
    )

    values = provider.resolve("env://SNOWFLAKE_USER/SNOWFLAKE_PASSWORD")

    assert values == {
        "SNOWFLAKE_USER": "analyst",
        "SNOWFLAKE_PASSWORD": "secret",
    }
    assert "OTHER" not in values


def test_aws_secrets_manager_provider_resolves_json_without_exposing_client_errors():
    class FakeClient:
        def get_secret_value(self, **kwargs):
            assert kwargs == {"SecretId": "acme/snowflake"}
            return {
                "SecretString": json.dumps(
                    {"SNOWFLAKE_USER": "analyst", "SNOWFLAKE_PASSWORD": "secret"}
                )
            }

    provider = AWSSecretsManagerCredentialProvider(client_factory=FakeClient)

    assert provider.resolve("aws-secrets://acme/snowflake")["SNOWFLAKE_USER"] == "analyst"


def test_azure_key_vault_provider_resolves_json_secret():
    class FakeClient:
        def get_secret(self, name, version):
            assert (name, version) == ("snowflake", None)
            return SimpleNamespace(value='{"SNOWFLAKE_PASSWORD":"secret"}')

    provider = AzureKeyVaultCredentialProvider(client_factory=lambda vault: FakeClient())

    assert provider.resolve("azure-key-vault://acme/snowflake") == {
        "SNOWFLAKE_PASSWORD": "secret"
    }


def test_vault_provider_resolves_kv_v2_secret():
    reader = SimpleNamespace(
        read_secret_version=lambda **kwargs: {
            "data": {"data": {"SNOWFLAKE_USER": "analyst"}}
        }
    )
    client = SimpleNamespace(secrets=SimpleNamespace(kv=SimpleNamespace(v2=reader)))
    provider = VaultCredentialProvider(client_factory=lambda: client)

    assert provider.resolve("vault://secret/acme/snowflake") == {
        "SNOWFLAKE_USER": "analyst"
    }


def test_credential_provider_registry_rejects_unknown_scheme():
    registry = CredentialProviderRegistry([])

    with pytest.raises(CredentialResolutionError, match="Unsupported credential"):
        registry.resolve("plaintext://unsafe")

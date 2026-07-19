from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import unquote, urlparse


class CredentialResolutionError(ValueError):
    pass


class CredentialProvider(Protocol):
    scheme: str

    def resolve(self, reference: str) -> dict[str, str]: ...


@dataclass(frozen=True)
class EnvironmentCredentialProvider:
    env: Mapping[str, str]
    scheme: str = "env"

    def resolve(self, reference: str) -> dict[str, str]:
        parsed = _reference(reference, self.scheme)
        keys = [unquote(part) for part in parsed.path.strip("/").split(",") if part]
        if parsed.netloc:
            keys.insert(0, unquote(parsed.netloc))
        if not keys:
            raise CredentialResolutionError("Environment credential reference has no keys.")
        missing = [key for key in keys if not str(self.env.get(key, "")).strip()]
        if missing:
            raise CredentialResolutionError(
                "Environment credential reference is missing required keys: "
                + ", ".join(missing)
            )
        return {key: str(self.env[key]).strip() for key in keys}


class AWSSecretsManagerCredentialProvider:
    scheme = "aws-secrets"

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory

    def resolve(self, reference: str) -> dict[str, str]:
        parsed = _reference(reference, self.scheme)
        secret_id = "/".join(part for part in (parsed.netloc, parsed.path.strip("/")) if part)
        if not secret_id:
            raise CredentialResolutionError("AWS secret reference has no secret id.")
        client = self._client_factory() if self._client_factory else self._default_client()
        try:
            response = client.get_secret_value(SecretId=secret_id)
        except Exception as exc:
            raise CredentialResolutionError(
                "AWS Secrets Manager could not resolve the reference."
            ) from exc
        value = response.get("SecretString")
        if value is None and response.get("SecretBinary") is not None:
            value = base64.b64decode(response["SecretBinary"]).decode("utf-8")
        return _credential_mapping(value, "AWS secret")

    @staticmethod
    def _default_client():
        try:
            import boto3
        except ImportError as exc:
            raise CredentialResolutionError(
                "AWS credential resolution requires the storage optional dependency."
            ) from exc
        return boto3.client("secretsmanager")


class AzureKeyVaultCredentialProvider:
    scheme = "azure-key-vault"

    def __init__(
        self,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self._client_factory = client_factory

    def resolve(self, reference: str) -> dict[str, str]:
        parsed = _reference(reference, self.scheme)
        vault_name = parsed.netloc.strip()
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if not vault_name or not parts:
            raise CredentialResolutionError(
                "Azure Key Vault reference requires a vault and secret name."
            )
        client = (
            self._client_factory(vault_name)
            if self._client_factory
            else self._default_client(vault_name)
        )
        try:
            secret = client.get_secret(parts[0], parts[1] if len(parts) > 1 else None)
        except Exception as exc:
            raise CredentialResolutionError(
                "Azure Key Vault could not resolve the reference."
            ) from exc
        return _credential_mapping(getattr(secret, "value", None), "Azure Key Vault secret")

    @staticmethod
    def _default_client(vault_name: str):
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient
        except ImportError as exc:
            raise CredentialResolutionError(
                "Azure credential resolution requires the secrets-azure optional dependency."
            ) from exc
        return SecretClient(
            vault_url=f"https://{vault_name}.vault.azure.net",
            credential=DefaultAzureCredential(),
        )


class VaultCredentialProvider:
    scheme = "vault"

    def __init__(self, client_factory: Callable[[], Any] | None = None) -> None:
        self._client_factory = client_factory

    def resolve(self, reference: str) -> dict[str, str]:
        parsed = _reference(reference, self.scheme)
        mount = parsed.netloc.strip() or "secret"
        path = parsed.path.strip("/")
        if not path:
            raise CredentialResolutionError("Vault reference has no secret path.")
        client = self._client_factory() if self._client_factory else self._default_client()
        try:
            response = client.secrets.kv.v2.read_secret_version(
                path=path,
                mount_point=mount,
            )
            values = response["data"]["data"]
        except Exception as exc:
            raise CredentialResolutionError("Vault could not resolve the reference.") from exc
        return _string_mapping(values, "Vault secret")

    @staticmethod
    def _default_client():
        try:
            import hvac
        except ImportError as exc:
            raise CredentialResolutionError(
                "Vault credential resolution requires the secrets-vault optional dependency."
            ) from exc
        return hvac.Client(
            url=os.getenv("VAULT_ADDR", "http://127.0.0.1:8200"),
            token=os.getenv("VAULT_TOKEN"),
        )


class CredentialProviderRegistry:
    def __init__(self, providers: list[CredentialProvider]) -> None:
        self._providers = {provider.scheme: provider for provider in providers}

    def resolve(self, reference: str) -> dict[str, str]:
        scheme = urlparse(reference).scheme.lower()
        provider = self._providers.get(scheme)
        if provider is None:
            raise CredentialResolutionError(
                f"Unsupported credential reference scheme: {scheme or '<missing>'}."
            )
        return provider.resolve(reference)


def build_default_credential_provider_registry(
    env: Mapping[str, str] | None = None,
) -> CredentialProviderRegistry:
    values = os.environ if env is None else env
    return CredentialProviderRegistry(
        [
            EnvironmentCredentialProvider(values),
            AWSSecretsManagerCredentialProvider(),
            AzureKeyVaultCredentialProvider(),
            VaultCredentialProvider(),
        ]
    )


def _reference(reference: str, expected_scheme: str):
    parsed = urlparse(reference.strip())
    if parsed.scheme.lower() != expected_scheme:
        raise CredentialResolutionError(
            f"Credential reference must use the {expected_scheme} scheme."
        )
    return parsed


def _credential_mapping(value: Any, label: str) -> dict[str, str]:
    if value is None or not str(value).strip():
        raise CredentialResolutionError(f"{label} is empty.")
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise CredentialResolutionError(f"{label} must contain a JSON object.") from exc
    return _string_mapping(parsed, label)


def _string_mapping(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise CredentialResolutionError(f"{label} must contain a non-empty object.")
    normalized = {
        str(key).strip(): str(item).strip()
        for key, item in value.items()
        if str(key).strip() and str(item).strip()
    }
    if not normalized:
        raise CredentialResolutionError(f"{label} has no usable credential values.")
    return normalized

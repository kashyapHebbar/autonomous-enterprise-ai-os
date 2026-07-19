from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aeai_os.security.auth import (
    AuthenticatedUser,
    AuthenticationError,
    parse_roles,
    parse_workspace_ids,
)


def authenticated_user_from_oidc_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks_url: str,
    roles_claim: str = "roles",
    organization_claim: str = "organization_id",
    workspaces_claim: str = "workspace_ids",
    claims: Mapping[str, Any] | None = None,
) -> AuthenticatedUser:
    """Verify an OIDC access token and map enterprise claims to platform identity."""
    verified = (
        dict(claims)
        if claims is not None
        else _verify_jwt(token, issuer, audience, jwks_url)
    )
    subject = _required_claim(verified, "sub")
    organization_id = _required_claim(verified, organization_claim)
    roles = _claim_values(verified.get(roles_claim))
    workspaces = parse_workspace_ids(_claim_values(verified.get(workspaces_claim)))
    name = str(verified.get("name") or verified.get("preferred_username") or subject).strip()
    return AuthenticatedUser(
        id=subject,
        name=name,
        roles=parse_roles(roles),
        organization_id=organization_id,
        workspace_ids=workspaces,
        workspace_id=workspaces[0],
    )


def bearer_token(headers: Mapping[str, str]) -> str:
    authorization = next(
        (value for key, value in headers.items() if key.lower() == "authorization"),
        "",
    )
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("OIDC authentication requires a Bearer access token.")
    return token.strip()


def _verify_jwt(token: str, issuer: str, audience: str, jwks_url: str) -> dict[str, Any]:
    try:
        import jwt
    except ImportError as exc:
        raise AuthenticationError(
            "OIDC support is not installed. Install the project identity dependency."
        ) from exc
    try:
        signing_key = jwt.PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:
        raise AuthenticationError("OIDC access token validation failed.") from exc


def _required_claim(claims: Mapping[str, Any], name: str) -> str:
    value = str(claims.get(name) or "").strip()
    if not value:
        raise AuthenticationError(f"OIDC token is missing required claim '{name}'.")
    return value


def _claim_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []

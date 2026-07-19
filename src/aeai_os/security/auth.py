from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from hmac import compare_digest
from typing import Any


class UserRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    REVIEWER = "reviewer"
    APPROVER = "approver"
    ADMIN = "admin"


class AuthPermission(StrEnum):
    READ_RUNS = "runs:read"
    MUTATE_RUNS = "runs:write"
    APPROVE_RUNS = "runs:approve"
    ADMINISTER = "administer"


ROLE_PERMISSIONS: dict[UserRole, frozenset[AuthPermission]] = {
    UserRole.VIEWER: frozenset({AuthPermission.READ_RUNS}),
    UserRole.OPERATOR: frozenset({AuthPermission.READ_RUNS, AuthPermission.MUTATE_RUNS}),
    UserRole.REVIEWER: frozenset({AuthPermission.READ_RUNS, AuthPermission.APPROVE_RUNS}),
    UserRole.APPROVER: frozenset({AuthPermission.READ_RUNS, AuthPermission.APPROVE_RUNS}),
    UserRole.ADMIN: frozenset(
        {
            AuthPermission.READ_RUNS,
            AuthPermission.MUTATE_RUNS,
            AuthPermission.APPROVE_RUNS,
            AuthPermission.ADMINISTER,
        }
    ),
}


class AuthenticationError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    name: str | None
    roles: tuple[UserRole, ...]
    organization_id: str = "local-org"
    workspace_ids: tuple[str, ...] = ("default",)
    workspace_id: str = "default"

    def has_permission(self, permission: AuthPermission) -> bool:
        return any(permission in ROLE_PERMISSIONS[role] for role in self.roles)

    def to_audit_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "roles": [role.value for role in self.roles],
            "organization_id": self.organization_id,
            "workspace_id": self.workspace_id,
        }

    def in_workspace(self, workspace_id: str | None) -> AuthenticatedUser:
        selected = _normalize_optional(workspace_id) or self.workspace_id
        if selected not in self.workspace_ids:
            raise AuthorizationError(
                f"User '{self.id}' does not have access to workspace '{selected}'."
            )
        return replace(self, workspace_id=selected)

    def can_access(self, organization_id: object, workspace_id: object) -> bool:
        return (
            organization_id == self.organization_id
            and workspace_id == self.workspace_id
        )


def parse_roles(raw_roles: str | Iterable[str]) -> tuple[UserRole, ...]:
    if isinstance(raw_roles, str):
        candidates = raw_roles.replace(";", ",").split(",")
    else:
        candidates = list(raw_roles)

    roles: list[UserRole] = []
    seen: set[UserRole] = set()
    for candidate in candidates:
        normalized = str(candidate).strip().lower()
        if not normalized:
            continue
        try:
            role = UserRole(normalized)
        except ValueError as exc:
            valid_roles = ", ".join(role.value for role in UserRole)
            raise AuthenticationError(
                f"Unknown role '{normalized}'. Valid roles: {valid_roles}."
            ) from exc
        if role not in seen:
            roles.append(role)
            seen.add(role)

    if not roles:
        raise AuthenticationError("At least one user role is required.")
    return tuple(roles)


def local_development_user(
    *,
    user_id: str,
    name: str | None,
    roles: str | Iterable[str],
    organization_id: str = "local-org",
    workspace_ids: str | Iterable[str] = ("default",),
) -> AuthenticatedUser:
    workspaces = parse_workspace_ids(workspace_ids)
    return AuthenticatedUser(
        id=_normalize_required(user_id, "Local user id"),
        name=_normalize_optional(name),
        roles=parse_roles(roles),
        organization_id=_normalize_required(organization_id, "Organization id"),
        workspace_ids=workspaces,
        workspace_id=workspaces[0],
    )


def authenticated_user_from_headers(
    headers: Mapping[str, str],
    *,
    auth_enabled: bool,
    token_profiles: str | Mapping[str, AuthenticatedUser],
    local_user_id: str,
    local_user_name: str | None,
    local_roles: str,
    local_organization_id: str = "local-org",
    local_workspace_ids: str = "default",
) -> AuthenticatedUser:
    if not auth_enabled:
        return local_development_user(
            user_id=local_user_id,
            name=local_user_name,
            roles=local_roles,
            organization_id=local_organization_id,
            workspace_ids=local_workspace_ids,
        )

    token = _bearer_token(headers) or _header(headers, "x-aeai-api-key")
    if token is None:
        raise AuthenticationError("Missing bearer token or X-AEAI-API-Key header.")

    profiles = (
        dict(token_profiles)
        if isinstance(token_profiles, Mapping)
        else parse_token_profiles(
            token_profiles,
            default_organization_id=local_organization_id,
            default_workspace_ids=local_workspace_ids,
        )
    )
    if not profiles:
        raise AuthenticationError("No authentication token profiles are configured.")

    for expected_token, user in profiles.items():
        if compare_digest(token, expected_token):
            return user
    raise AuthenticationError("Invalid authentication credentials.")


def parse_token_profiles(
    raw_profiles: str,
    *,
    default_organization_id: str = "local-org",
    default_workspace_ids: str = "default",
) -> dict[str, AuthenticatedUser]:
    """Parse token=user|name|roles[|organization|workspaces] entries."""
    profiles: dict[str, AuthenticatedUser] = {}
    for raw_profile in raw_profiles.split(";"):
        profile = raw_profile.strip()
        if not profile:
            continue
        token, separator, user_spec = profile.partition("=")
        if not separator:
            raise AuthenticationError(
                "Token profiles must use token=user_id|display_name|roles format."
            )
        normalized_token = _normalize_required(token, "Auth token")
        parts = [part.strip() for part in user_spec.split("|")]
        if len(parts) not in {3, 5}:
            raise AuthenticationError(
                "Token profiles must include user id, display name, roles, and optionally "
                "organization id and comma-separated workspace ids."
            )
        if normalized_token in profiles:
            raise AuthenticationError("Duplicate auth token profile configured.")
        user_id, user_name, roles = parts[:3]
        organization_id = parts[3] if len(parts) == 5 else default_organization_id
        raw_workspaces = parts[4] if len(parts) == 5 else default_workspace_ids
        workspaces = parse_workspace_ids(raw_workspaces)
        profiles[normalized_token] = AuthenticatedUser(
            id=_normalize_required(user_id, "User id"),
            name=_normalize_optional(user_name)
            or _normalize_required(user_id, "User id"),
            roles=parse_roles(roles),
            organization_id=_normalize_required(organization_id, "Organization id"),
            workspace_ids=workspaces,
            workspace_id=workspaces[0],
        )
    return profiles


def parse_workspace_ids(raw_workspace_ids: str | Iterable[str]) -> tuple[str, ...]:
    candidates = (
        raw_workspace_ids.replace(";", ",").split(",")
        if isinstance(raw_workspace_ids, str)
        else list(raw_workspace_ids)
    )
    workspaces = tuple(
        dict.fromkeys(str(value).strip() for value in candidates if str(value).strip())
    )
    if not workspaces:
        raise AuthenticationError("At least one workspace id is required.")
    return workspaces


def _bearer_token(headers: Mapping[str, str]) -> str | None:
    authorization = _header(headers, "authorization")
    if authorization is None:
        return None

    scheme, separator, credentials = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        raise AuthenticationError("Authorization header must use the Bearer scheme.")
    token = credentials.strip()
    if not token:
        raise AuthenticationError("Bearer token must not be blank.")
    return token


def ensure_permission(user: AuthenticatedUser, permission: AuthPermission) -> None:
    if not user.has_permission(permission):
        roles = ", ".join(role.value for role in user.roles)
        raise AuthorizationError(
            f"User '{user.id}' with roles [{roles}] lacks permission '{permission.value}'."
        )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    direct = headers.get(name)
    if direct is not None:
        return direct

    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _normalize_required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise AuthenticationError(f"{label} must not be blank.")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class UserRole(StrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
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

    def has_permission(self, permission: AuthPermission) -> bool:
        return any(permission in ROLE_PERMISSIONS[role] for role in self.roles)

    def to_audit_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "roles": [role.value for role in self.roles],
        }


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
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=_normalize_required(user_id, "Local user id"),
        name=_normalize_optional(name),
        roles=parse_roles(roles),
    )


def authenticated_user_from_headers(
    headers: Mapping[str, str],
    *,
    auth_enabled: bool,
    local_user_id: str,
    local_user_name: str | None,
    local_roles: str,
) -> AuthenticatedUser:
    if not auth_enabled:
        return local_development_user(
            user_id=local_user_id,
            name=local_user_name,
            roles=local_roles,
        )

    user_id = _header(headers, "x-aeai-user-id")
    if user_id is None:
        raise AuthenticationError("Missing X-AEAI-User-Id header.")

    roles = _header(headers, "x-aeai-roles") or _header(headers, "x-aeai-role")
    if roles is None:
        raise AuthenticationError("Missing X-AEAI-Roles header.")

    user_name = _header(headers, "x-aeai-user-name")
    return AuthenticatedUser(
        id=_normalize_required(user_id, "User id"),
        name=_normalize_optional(user_name) or _normalize_required(user_id, "User id"),
        roles=parse_roles(roles),
    )


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

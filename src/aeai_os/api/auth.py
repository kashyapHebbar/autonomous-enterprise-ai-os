from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from aeai_os.security.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthorizationError,
    AuthPermission,
    authenticated_user_from_headers,
    ensure_permission,
)
from aeai_os.settings import get_settings


def get_current_user(request: Request) -> AuthenticatedUser:
    settings = get_settings()
    try:
        return authenticated_user_from_headers(
            request.headers,
            auth_enabled=settings.auth_enabled,
            token_profiles=settings.auth_token_profiles,
            local_user_id=settings.auth_local_user_id,
            local_user_name=settings.auth_local_user_name,
            local_roles=settings.auth_local_roles,
        )
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def require_permission(
    permission: AuthPermission,
) -> Callable[[AuthenticatedUser], AuthenticatedUser]:
    def dependency(
        user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    ) -> AuthenticatedUser:
        try:
            ensure_permission(user, permission)
        except AuthorizationError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc
        return user

    return dependency


RunReader = Annotated[
    AuthenticatedUser,
    Depends(require_permission(AuthPermission.READ_RUNS)),
]
RunWriter = Annotated[
    AuthenticatedUser,
    Depends(require_permission(AuthPermission.MUTATE_RUNS)),
]
RunApprover = Annotated[
    AuthenticatedUser,
    Depends(require_permission(AuthPermission.APPROVE_RUNS)),
]
AdminUser = Annotated[
    AuthenticatedUser,
    Depends(require_permission(AuthPermission.ADMINISTER)),
]

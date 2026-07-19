from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from aeai_os.security.auth import (
    AuthenticatedUser,
    AuthenticationError,
    AuthorizationError,
    AuthPermission,
    authenticated_user_from_headers,
    ensure_permission,
)
from aeai_os.security.oidc import authenticated_user_from_oidc_token, bearer_token
from aeai_os.settings import get_settings


def get_current_user(request: Request) -> AuthenticatedUser:
    settings = get_settings()
    try:
        if settings.auth_mode == "oidc":
            user = authenticated_user_from_oidc_token(
                bearer_token(request.headers),
                issuer=settings.oidc_issuer,
                audience=settings.oidc_audience,
                jwks_url=settings.oidc_jwks_url,
                roles_claim=settings.oidc_roles_claim,
                organization_claim=settings.oidc_organization_claim,
                workspaces_claim=settings.oidc_workspaces_claim,
            )
        else:
            user = authenticated_user_from_headers(
                request.headers,
                auth_enabled=settings.auth_mode == "token",
                token_profiles=settings.auth_token_profiles,
                local_user_id=settings.auth_local_user_id,
                local_user_name=settings.auth_local_user_name,
                local_roles=settings.auth_local_roles,
                local_organization_id=settings.auth_local_organization_id,
                local_workspace_ids=settings.auth_local_workspace_ids,
            )
        return user.in_workspace(request.headers.get("X-AEAI-Workspace-ID"))
    except (AuthenticationError, AuthorizationError) as exc:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if isinstance(exc, AuthorizationError)
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


class SessionResponse(BaseModel):
    user_id: str
    name: str | None
    roles: list[str]
    organization_id: str
    workspace_ids: list[str]
    active_workspace_id: str
    permissions: list[str]


def build_auth_router() -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])

    @router.get("/me", response_model=SessionResponse)
    def current_session(user: Annotated[AuthenticatedUser, Depends(get_current_user)]):
        return SessionResponse(
            user_id=user.id,
            name=user.name,
            roles=[role.value for role in user.roles],
            organization_id=user.organization_id,
            workspace_ids=list(user.workspace_ids),
            active_workspace_id=user.workspace_id,
            permissions=[
                permission.value
                for permission in AuthPermission
                if user.has_permission(permission)
            ],
        )

    return router


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

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field

from aeai_os.api.auth import AdminUser, RunReader
from aeai_os.connectors import (
    ConnectorHealth,
    ConnectorInstallation,
    ConnectorInstallationError,
    ConnectorInstallationNotFoundError,
    ConnectorRegistry,
)
from aeai_os.security.redaction import redact_text, redact_value


class ConnectorResponse(BaseModel):
    id: str
    name: str
    provider: str
    kind: str
    credential_profile_id: str | None
    capabilities: list[str]
    configuration_fields: list[dict[str, Any]] = Field(default_factory=list)
    credential_required: bool = False
    auth_methods: list[str] = Field(default_factory=list)
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class CredentialProfileResponse(BaseModel):
    id: str
    provider: str
    credential_type: str
    description: str
    configured: bool
    configured_env_keys: list[str]
    missing_env_keys: list[str]
    secret_env_keys: list[str]


class ConnectorHealthResponse(BaseModel):
    connector_id: str
    status: str
    message: str
    checked_at: datetime
    details: dict[str, Any]


class CreateConnectorInstallationRequest(BaseModel):
    connector_id: str = Field(..., min_length=2, max_length=100)
    name: str = Field(..., min_length=2, max_length=200)
    credential_reference: str | None = Field(default=None, max_length=500)
    configuration: dict[str, str] = Field(default_factory=dict)


class ConnectorInstallationResponse(BaseModel):
    id: str
    connector_id: str
    name: str
    organization_id: str
    workspace_id: str | None
    credential_reference: str | None
    configuration: dict[str, str]
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


def build_connectors_router(registry: ConnectorRegistry) -> APIRouter:
    router = APIRouter(prefix="/connectors", tags=["connectors"])

    @router.get("", response_model=list[ConnectorResponse])
    def list_connectors(user: RunReader) -> list[ConnectorResponse]:
        return [
            ConnectorResponse(**registry.connector_summary(connector))
            for connector in registry.list_connectors()
        ]

    @router.get("/credential-profiles", response_model=list[CredentialProfileResponse])
    def list_credential_profiles(user: RunReader) -> list[CredentialProfileResponse]:
        return [
            CredentialProfileResponse(**profile)
            for profile in registry.list_credential_profiles()
        ]

    @router.post(
        "/installations",
        response_model=ConnectorInstallationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_installation(
        request: Annotated[CreateConnectorInstallationRequest, Body(...)],
        actor: AdminUser,
    ) -> ConnectorInstallationResponse:
        try:
            installation = registry.create_installation(
                connector_id=request.connector_id,
                name=request.name,
                organization_id=actor.organization_id,
                workspace_id=actor.workspace_id,
                credential_reference=request.credential_reference,
                configuration=request.configuration,
                created_by=actor.id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ConnectorInstallationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return _installation_to_response(installation)

    @router.get("/installations", response_model=list[ConnectorInstallationResponse])
    def list_installations(user: RunReader) -> list[ConnectorInstallationResponse]:
        return [
            _installation_to_response(installation)
            for installation in registry.list_installations(user.organization_id)
            if installation.workspace_id in {None, user.workspace_id}
        ]

    @router.post(
        "/installations/{installation_id}/test",
        response_model=ConnectorHealthResponse,
    )
    def test_installation(
        installation_id: str,
        actor: AdminUser,
    ) -> ConnectorHealthResponse:
        try:
            installation = registry.get_installation(
                installation_id, actor.organization_id
            )
            if installation.workspace_id not in {None, actor.workspace_id}:
                raise ConnectorInstallationNotFoundError(
                    f"Connector installation not found: {installation_id}"
                )
            return _health_to_response(
                registry.test_installation(installation_id, actor.organization_id)
            )
        except ConnectorInstallationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @router.get("/{connector_id}/health", response_model=ConnectorHealthResponse)
    def connector_health(connector_id: str, user: RunReader) -> ConnectorHealthResponse:
        try:
            health = registry.health(connector_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        return _health_to_response(health)

    return router


def _health_to_response(health: ConnectorHealth) -> ConnectorHealthResponse:
    return ConnectorHealthResponse(
        connector_id=health.connector_id,
            status=health.status,
            message=redact_text(health.message) or "",
            checked_at=health.checked_at,
        details=redact_value(health.details),
    )


def _installation_to_response(
    installation: ConnectorInstallation,
) -> ConnectorInstallationResponse:
    return ConnectorInstallationResponse(
        id=installation.id,
        connector_id=installation.connector_id,
        name=installation.name,
        organization_id=installation.organization_id,
        workspace_id=installation.workspace_id,
        credential_reference=redact_text(installation.credential_reference),
        configuration=redact_value(installation.configuration),
        status=installation.status,
        created_by=installation.created_by,
        created_at=installation.created_at,
        updated_at=installation.updated_at,
    )

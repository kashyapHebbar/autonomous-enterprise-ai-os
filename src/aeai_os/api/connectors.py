from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aeai_os.api.auth import RunReader
from aeai_os.connectors import ConnectorHealth, ConnectorRegistry


class ConnectorResponse(BaseModel):
    id: str
    name: str
    provider: str
    kind: str
    credential_profile_id: str | None
    capabilities: list[str]
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
        message=health.message,
        checked_at=health.checked_at,
        details=health.details,
    )

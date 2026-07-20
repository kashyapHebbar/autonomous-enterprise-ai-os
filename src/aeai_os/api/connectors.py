from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, Field

from aeai_os.api.auth import AdminUser, RunReader
from aeai_os.connectors import (
    ConnectorHealth,
    ConnectorInstallation,
    ConnectorInstallationError,
    ConnectorInstallationNotFoundError,
    ConnectorRegistry,
)
from aeai_os.connectors.explorer import ConnectorExplorer
from aeai_os.data.sources import (
    DataSourceAlreadyExistsError,
    DataSourceRegistry,
    DataSourceValidationError,
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


class ConnectorAssetResponse(BaseModel):
    id: str
    name: str
    kind: str
    path: str
    can_browse: bool
    can_preview: bool
    can_select: bool
    metadata: dict[str, Any]


class ConnectorBrowseResponse(BaseModel):
    installation_id: str
    connector_id: str
    path: str
    assets: list[ConnectorAssetResponse]


class ConnectorPreviewRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=1000)
    limit: int = Field(default=25, ge=1, le=100)


class ConnectorPreviewResponse(BaseModel):
    installation_id: str
    connector_id: str
    asset_id: str
    asset_name: str
    columns: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    truncated: bool


class RegisterConnectorAssetRequest(BaseModel):
    asset_id: str = Field(..., min_length=1, max_length=1000)
    data_source_id: str = Field(..., min_length=3, max_length=100)
    name: str = Field(..., min_length=3, max_length=200)
    owner: str = Field(..., min_length=2, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_connectors_router(
    registry: ConnectorRegistry,
    data_source_registry: DataSourceRegistry | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/connectors", tags=["connectors"])
    explorer = ConnectorExplorer(registry)

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
        probe: bool = Query(default=False),
    ) -> ConnectorHealthResponse:
        try:
            installation = _tenant_installation(registry, installation_id, actor)
            health = registry.test_installation(installation_id, actor.organization_id)
            if probe and health.status == "ok":
                health = explorer.test(installation)
            return _health_to_response(health)
        except ConnectorInstallationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @router.get(
        "/installations/{installation_id}/browse",
        response_model=ConnectorBrowseResponse,
    )
    def browse_installation(
        installation_id: str,
        actor: AdminUser,
        path: str = Query(default="", max_length=1000),
    ) -> ConnectorBrowseResponse:
        try:
            installation = _tenant_installation(registry, installation_id, actor)
            result = explorer.browse(installation, path)
        except ConnectorInstallationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ConnectorInstallationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return ConnectorBrowseResponse(
            installation_id=result.installation_id,
            connector_id=result.connector_id,
            path=result.path,
            assets=[ConnectorAssetResponse(**asset.__dict__) for asset in result.assets],
        )

    @router.post(
        "/installations/{installation_id}/preview",
        response_model=ConnectorPreviewResponse,
    )
    def preview_installation_asset(
        installation_id: str,
        request: Annotated[ConnectorPreviewRequest, Body(...)],
        actor: AdminUser,
    ) -> ConnectorPreviewResponse:
        try:
            installation = _tenant_installation(registry, installation_id, actor)
            preview = explorer.preview(
                installation, request.asset_id, limit=request.limit
            )
        except ConnectorInstallationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (ConnectorInstallationError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return ConnectorPreviewResponse(
            installation_id=preview.installation_id,
            connector_id=preview.connector_id,
            asset_id=preview.asset_id,
            asset_name=preview.asset_name,
            columns=[column.__dict__ for column in preview.columns],
            rows=redact_value(preview.rows),
            truncated=preview.truncated,
        )

    @router.post(
        "/installations/{installation_id}/sources",
        status_code=status.HTTP_201_CREATED,
    )
    def register_installation_asset(
        installation_id: str,
        request: Annotated[RegisterConnectorAssetRequest, Body(...)],
        actor: AdminUser,
    ) -> dict[str, Any]:
        if data_source_registry is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Data source registration is unavailable.",
            )
        try:
            installation = _tenant_installation(registry, installation_id, actor)
            spec = explorer.registration_spec(installation, request.asset_id)
            source = data_source_registry.register(
                data_source_id=request.data_source_id,
                name=request.name,
                source_type=spec.source_type,
                dataset_uri=spec.dataset_uri,
                owner=request.owner,
                organization_id=actor.organization_id,
                workspace_id=actor.workspace_id,
                connector_id=spec.connector_id,
                credential_profile_id=spec.credential_profile_id,
                metadata={**request.metadata, **spec.metadata},
            )
        except ConnectorInstallationNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except DataSourceAlreadyExistsError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except DataSourceValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "status": exc.result.status,
                    "message": exc.result.message,
                    "details": redact_value(exc.result.details),
                },
            ) from exc
        except (ConnectorInstallationError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        return {
            "id": source.id,
            "name": source.name,
            "source_type": source.source_type,
            "connector_id": source.connector_id,
            "credential_profile_id": source.credential_profile_id,
            "dataset_uri": redact_text(source.dataset_uri),
            "owner": source.owner,
            "organization_id": source.organization_id,
            "workspace_id": source.workspace_id,
            "metadata": redact_value(source.metadata),
            "created_at": source.created_at,
            "updated_at": source.updated_at,
            "latest_validation": {
                "status": source.latest_validation.status,
                "message": source.latest_validation.message,
                "checked_at": source.latest_validation.checked_at,
                "details": redact_value(source.latest_validation.details),
            }
            if source.latest_validation
            else None,
        }

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


def _tenant_installation(
    registry: ConnectorRegistry,
    installation_id: str,
    actor: AdminUser,
) -> ConnectorInstallation:
    installation = registry.get_installation(installation_id, actor.organization_id)
    if installation.workspace_id not in {None, actor.workspace_id}:
        raise ConnectorInstallationNotFoundError(
            f"Connector installation not found: {installation_id}"
        )
    return installation


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

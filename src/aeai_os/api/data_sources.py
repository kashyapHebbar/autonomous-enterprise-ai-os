from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from aeai_os.api.auth import RunReader, RunWriter
from aeai_os.data.sources import (
    DataSourceAlreadyExistsError,
    DataSourceNotFoundError,
    DataSourceRecord,
    DataSourceRegistry,
    DataSourceType,
    DataSourceValidationError,
    DataSourceValidationResult,
)


class CreateDataSourceRequest(BaseModel):
    id: str = Field(..., min_length=3, max_length=100)
    name: str = Field(..., min_length=3, max_length=200)
    source_type: DataSourceType
    dataset_uri: str = Field(..., max_length=2048)
    owner: str = Field(..., min_length=2, max_length=200)
    connector_id: str | None = Field(default=None, max_length=100)
    credential_profile_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "name", "dataset_uri", "owner")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required.")
        return normalized

    @field_validator("source_type", mode="before")
    @classmethod
    def normalize_source_type(cls, value: str) -> str:
        normalized = str(value).strip().lower().replace("-", "_")
        aliases = {
            "local": "local_file",
            "file": "local_file",
            "csv": "local_file",
            "warehouse_sqlite": "sqlite",
            "snowflake_warehouse": "snowflake",
        }
        return aliases.get(normalized, normalized)

    @field_validator("connector_id", "credential_profile_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DataSourceValidationResponse(BaseModel):
    status: Literal["ok", "invalid"]
    message: str
    checked_at: datetime
    details: dict[str, Any]


class DataSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    connector_id: str
    credential_profile_id: str | None
    dataset_uri: str
    owner: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    latest_validation: DataSourceValidationResponse | None = None


def build_data_sources_router(registry: DataSourceRegistry) -> APIRouter:
    router = APIRouter(prefix="/data-sources", tags=["data-sources"])

    @router.post("", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
    def register_data_source(
        request: Annotated[CreateDataSourceRequest, Body(...)],
        actor: RunWriter,
    ) -> DataSourceResponse:
        del actor
        try:
            source = registry.register(
                data_source_id=request.id,
                name=request.name,
                source_type=request.source_type,
                dataset_uri=request.dataset_uri,
                owner=request.owner,
                connector_id=request.connector_id,
                credential_profile_id=request.credential_profile_id,
                metadata=request.metadata,
            )
        except DataSourceValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_validation_to_response(exc.result).model_dump(mode="json"),
            ) from exc
        except DataSourceAlreadyExistsError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        return _source_to_response(source)

    @router.get("", response_model=list[DataSourceResponse])
    def list_data_sources(user: RunReader) -> list[DataSourceResponse]:
        del user
        return [_source_to_response(source) for source in registry.list_sources()]

    @router.get("/{data_source_id}", response_model=DataSourceResponse)
    def get_data_source(data_source_id: str, user: RunReader) -> DataSourceResponse:
        del user
        try:
            return _source_to_response(registry.get(data_source_id))
        except DataSourceNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @router.post(
        "/{data_source_id}/validate",
        response_model=DataSourceValidationResponse,
    )
    def validate_data_source(
        data_source_id: str,
        actor: RunWriter,
    ) -> DataSourceValidationResponse:
        del actor
        try:
            return _validation_to_response(registry.validate(data_source_id))
        except DataSourceNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    return router


def _source_to_response(source: DataSourceRecord) -> DataSourceResponse:
    return DataSourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        connector_id=source.connector_id,
        credential_profile_id=source.credential_profile_id,
        dataset_uri=source.dataset_uri,
        owner=source.owner,
        metadata=source.metadata,
        created_at=source.created_at,
        updated_at=source.updated_at,
        latest_validation=(
            _validation_to_response(source.latest_validation)
            if source.latest_validation is not None
            else None
        ),
    )


def _validation_to_response(
    validation: DataSourceValidationResult,
) -> DataSourceValidationResponse:
    return DataSourceValidationResponse(
        status=validation.status,
        message=validation.message,
        checked_at=validation.checked_at,
        details=validation.details,
    )

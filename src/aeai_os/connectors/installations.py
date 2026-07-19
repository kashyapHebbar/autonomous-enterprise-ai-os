from __future__ import annotations

from typing import Protocol

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from aeai_os.connectors.registry import (
    ConnectorInstallation,
    ConnectorInstallationNotFoundError,
)
from aeai_os.settings import AppSettings
from aeai_os.storage.sqlalchemy_models import Base, ConnectorInstallationModel


class ConnectorInstallationRepository(Protocol):
    def save(self, installation: ConnectorInstallation) -> ConnectorInstallation: ...

    def list(self, organization_id: str) -> list[ConnectorInstallation]: ...

    def get(self, installation_id: str, organization_id: str) -> ConnectorInstallation: ...


class InMemoryConnectorInstallationRepository:
    def __init__(self) -> None:
        self._installations: dict[str, ConnectorInstallation] = {}

    def save(self, installation: ConnectorInstallation) -> ConnectorInstallation:
        self._installations[installation.id] = installation
        return installation

    def list(self, organization_id: str) -> list[ConnectorInstallation]:
        return sorted(
            (
                installation
                for installation in self._installations.values()
                if installation.organization_id == organization_id
            ),
            key=lambda installation: (installation.name.lower(), installation.id),
        )

    def get(self, installation_id: str, organization_id: str) -> ConnectorInstallation:
        installation = self._installations.get(installation_id)
        if installation is None or installation.organization_id != organization_id:
            raise ConnectorInstallationNotFoundError(
                f"Connector installation not found: {installation_id}"
            )
        return installation


class SQLAlchemyConnectorInstallationRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_engine(
        cls, engine: Engine, *, create_schema: bool = False
    ) -> SQLAlchemyConnectorInstallationRepository:
        if create_schema:
            Base.metadata.create_all(engine)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    @classmethod
    def from_url(
        cls, database_url: str, *, create_schema: bool = False
    ) -> SQLAlchemyConnectorInstallationRepository:
        return cls.from_engine(create_engine(database_url), create_schema=create_schema)

    def save(self, installation: ConnectorInstallation) -> ConnectorInstallation:
        model = _to_model(installation)
        with self._session_factory() as session:
            model = session.merge(model)
            session.commit()
            return _from_model(model)

    def list(self, organization_id: str) -> list[ConnectorInstallation]:
        with self._session_factory() as session:
            models = session.scalars(
                select(ConnectorInstallationModel)
                .where(ConnectorInstallationModel.organization_id == organization_id)
                .order_by(ConnectorInstallationModel.name, ConnectorInstallationModel.id)
            ).all()
            return [_from_model(model) for model in models]

    def get(self, installation_id: str, organization_id: str) -> ConnectorInstallation:
        with self._session_factory() as session:
            model = session.scalar(
                select(ConnectorInstallationModel).where(
                    ConnectorInstallationModel.id == installation_id,
                    ConnectorInstallationModel.organization_id == organization_id,
                )
            )
            if model is None:
                raise ConnectorInstallationNotFoundError(
                    f"Connector installation not found: {installation_id}"
                )
            return _from_model(model)


def build_connector_installation_repository(settings: AppSettings):
    backend = settings.run_repository_backend.strip().lower()
    if backend in {"memory", "in-memory", "in_memory"}:
        return InMemoryConnectorInstallationRepository()
    if backend == "sqlalchemy":
        return SQLAlchemyConnectorInstallationRepository.from_url(
            settings.database_url,
            create_schema=settings.run_repository_create_schema,
        )
    raise ValueError(f"Unsupported connector installation backend: {backend}")


def _to_model(installation: ConnectorInstallation) -> ConnectorInstallationModel:
    return ConnectorInstallationModel(
        id=installation.id,
        connector_id=installation.connector_id,
        name=installation.name,
        organization_id=installation.organization_id,
        workspace_id=installation.workspace_id,
        credential_reference=installation.credential_reference,
        configuration_json=dict(installation.configuration),
        status=installation.status,
        created_by=installation.created_by,
        created_at=installation.created_at,
        updated_at=installation.updated_at,
    )


def _from_model(model: ConnectorInstallationModel) -> ConnectorInstallation:
    return ConnectorInstallation(
        id=model.id,
        connector_id=model.connector_id,
        name=model.name,
        organization_id=model.organization_id,
        workspace_id=model.workspace_id,
        credential_reference=model.credential_reference,
        configuration=dict(model.configuration_json),
        status=model.status,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )

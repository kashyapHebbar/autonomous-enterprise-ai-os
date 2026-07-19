from datetime import UTC, datetime

from sqlalchemy import create_engine

from aeai_os.connectors import ConnectorInstallation
from aeai_os.connectors.installations import SQLAlchemyConnectorInstallationRepository


def test_sqlalchemy_connector_installations_survive_repository_recreation():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SQLAlchemyConnectorInstallationRepository.from_engine(
        engine,
        create_schema=True,
    )
    now = datetime.now(UTC)
    installation = ConnectorInstallation(
        id="conn_finance",
        connector_id="snowflake-default",
        name="Finance warehouse",
        organization_id="acme",
        workspace_id="finance",
        credential_reference="aws-secrets://acme/snowflake",
        configuration={"database": "ANALYTICS"},
        status="ready",
        created_by="admin-1",
        created_at=now,
        updated_at=now,
    )
    repository.save(installation)

    recreated = SQLAlchemyConnectorInstallationRepository.from_engine(engine)

    assert recreated.get("conn_finance", "acme").configuration == {
        "database": "ANALYTICS"
    }
    assert recreated.list("other-org") == []

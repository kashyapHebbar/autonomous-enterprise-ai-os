from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

from sqlalchemy import create_engine, inspect

from aeai_os.runs.models import AgentEventRecord, EvaluationResultRecord, GraphNodeRecord
from aeai_os.runs.repository import utc_now
from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository
from aeai_os.schemas.enums import (
    AgentEventType,
    ArtifactType,
    GraphNodeStatus,
    RunStatus,
)
from aeai_os.storage.migrations import validate_persistent_schema


def test_database_migration_command_initializes_clean_database(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'platform.db'}"

    upgrade = subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database-url",
            database_url,
            "upgrade",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    validate = subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database-url",
            database_url,
            "validate",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    engine = create_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert upgrade.returncode == 0, upgrade.stderr
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "alembic_version" in table_names
    assert validate_persistent_schema(database_url) == []


def test_migrated_schema_supports_current_repository_model(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'repository.db'}"
    subprocess.run(
        [
            sys.executable,
            "scripts/manage_database.py",
            "--database-url",
            database_url,
            "upgrade",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    repository = SQLAlchemyRunRepository.from_url(database_url, create_schema=False)
    run = repository.create_run("Analyze procurement data.", metadata={"source": "migration"})
    artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="s3://bucket/procurement.csv",
        metadata={"format": "csv"},
    )
    created_at = utc_now()
    node = GraphNodeRecord(
        id="profile",
        run_id=run.id,
        agent_type="data_retrieval",
        status=GraphNodeStatus.PENDING,
        depends_on=[],
        required_tools=["snowflake_query"],
        expected_artifacts=["schema_profile"],
        retry_count=0,
        created_at=created_at,
        updated_at=created_at,
    )
    event = AgentEventRecord(
        id="event_profile_started",
        run_id=run.id,
        node_id="profile",
        event_type=AgentEventType.LOG.value,
        payload={"message": "started"},
        created_at=created_at,
    )
    evaluation = EvaluationResultRecord(
        id="evaluation_profile",
        run_id=run.id,
        target_artifact_id=artifact.id,
        score=0.91,
        passed=True,
        checks=[{"name": "schema", "passed": True}],
    )

    repository.add_graph_node(node)
    repository.upsert_graph_node(replace(node, status=GraphNodeStatus.COMPLETED))
    repository.add_event(event)
    repository.save_checkpoint(run.id, {"run_id": run.id, "completed_node_ids": ["profile"]})
    repository.add_evaluation(evaluation)
    repository.update_status(run.id, RunStatus.COMPLETED)

    assert repository.get_run(run.id).status == RunStatus.COMPLETED
    assert repository.list_artifacts(run.id) == [artifact]
    assert repository.list_graph_nodes(run.id)[0].status == GraphNodeStatus.COMPLETED
    assert repository.list_events(run.id)[0] == event
    assert repository.get_checkpoint(run.id).state["completed_node_ids"] == ["profile"]
    assert repository.list_evaluations(run.id)[0].score == 0.91


def test_schema_validation_reports_missing_persistent_tables(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'empty.db'}"
    engine = create_engine(database_url)
    engine.dispose()

    errors = validate_persistent_schema(database_url)

    assert "Missing table: runs" in errors
    assert "Missing table: workflow_jobs" in errors

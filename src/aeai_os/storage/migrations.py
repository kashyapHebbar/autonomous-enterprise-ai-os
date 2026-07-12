from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATION_SCRIPT_LOCATION = PROJECT_ROOT / "migrations"

EXPECTED_TABLES = {
    "runs",
    "graph_nodes",
    "artifacts",
    "workflow_jobs",
    "agent_events",
    "run_checkpoints",
    "evaluation_results",
}

EXPECTED_INDEXES: Mapping[str, set[str]] = {
    "runs": {"ix_runs_status"},
    "graph_nodes": {"ix_graph_nodes_run_id", "ix_graph_nodes_status"},
    "artifacts": {
        "ix_artifacts_run_id",
        "ix_artifacts_type",
        "ix_artifacts_storage_backend",
    },
    "workflow_jobs": {
        "ix_workflow_jobs_run_id",
        "ix_workflow_jobs_workflow_name",
        "ix_workflow_jobs_status",
    },
    "agent_events": {"ix_agent_events_run_id", "ix_agent_events_node_id"},
    "evaluation_results": {"ix_evaluation_results_run_id"},
}

EXPECTED_COLUMNS: Mapping[str, set[str]] = {
    "artifacts": {
        "content_type",
        "storage_backend",
        "storage_key",
        "size_bytes",
        "source_artifact_ids",
        "producer_node_id",
        "metadata_json",
    },
}


def build_alembic_config(database_url: str) -> Any:
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(MIGRATION_SCRIPT_LOCATION))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_database(database_url: str, revision: str = "head") -> None:
    from alembic import command

    command.upgrade(build_alembic_config(database_url), revision)


def validate_persistent_schema(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        return validate_persistent_schema_engine(engine)
    finally:
        engine.dispose()


def validate_persistent_schema_engine(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    errors: list[str] = []

    for table_name in sorted(EXPECTED_TABLES - existing_tables):
        errors.append(f"Missing table: {table_name}")

    for table_name, expected_indexes in EXPECTED_INDEXES.items():
        if table_name not in existing_tables:
            continue
        existing_indexes = {
            index["name"]
            for index in inspector.get_indexes(table_name)
            if index.get("name") is not None
        }
        for index_name in sorted(expected_indexes - existing_indexes):
            errors.append(f"Missing index: {table_name}.{index_name}")

    for table_name, expected_columns in EXPECTED_COLUMNS.items():
        if table_name not in existing_tables:
            continue
        existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column_name in sorted(expected_columns - existing_columns):
            errors.append(f"Missing column: {table_name}.{column_name}")

    return errors

from __future__ import annotations

import json
import sqlite3

import pytest

from aeai_os.agents.base import AgentInput
from aeai_os.agents.data_retrieval import DataRetrievalAgent
from aeai_os.data import CsvDatasetAdapter, DataIngestionError
from aeai_os.data.profiling import profile_csv_dataset, profile_tabular_rows
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType


def write_procurement_csv(path):
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-10,1200.50,IT",
                "Zenith,Hardware,2026-01-11,800.00,Operations",
                "Acme,Software,2026-01-12,300.00,IT",
            ]
        ),
        encoding="utf-8",
    )


def write_procurement_sqlite(path):
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE procurement (
                supplier TEXT,
                category TEXT,
                invoice_date TEXT,
                spend_amount REAL,
                department TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO procurement VALUES (?, ?, ?, ?, ?)",
            [
                ("Acme", "Software", "2026-01-10", 1200.50, "IT"),
                ("Zenith", "Hardware", "2026-01-11", 800.00, "Operations"),
                ("Acme", "Software", "2026-01-12", 300.00, "IT"),
            ],
        )


def test_profile_csv_dataset_infers_schema_quality_and_statistics(tmp_path):
    csv_path = tmp_path / "procurement.csv"
    write_procurement_csv(csv_path)

    profile = profile_csv_dataset(csv_path)
    schema = profile.schema_artifact()
    quality = profile.quality_artifact()
    spend_column = next(column for column in schema["columns"] if column["name"] == "spend_amount")

    assert profile.row_count == 3
    assert profile.column_count == 5
    assert spend_column["type"] == "number"
    assert spend_column["summary_statistics"]["sum"] == 2300.5
    assert quality["missing_cells"] == 0
    assert quality["duplicate_row_count"] == 0


def test_profile_tabular_rows_reuses_csv_quality_contract():
    profile = profile_tabular_rows(
        source_path="sqlite://warehouse#procurement",
        rows=[
            {"supplier": "Acme", "spend_amount": 1200.50},
            {"supplier": "Zenith", "spend_amount": 800.00},
            {"supplier": "", "spend_amount": None},
        ],
        fieldnames=["supplier", "spend_amount"],
    )
    quality = profile.quality_artifact()
    schema_columns = profile.schema_artifact()["columns"]
    spend_column = next(column for column in schema_columns if column["name"] == "spend_amount")

    assert profile.row_count == 3
    assert quality["missing_cells"] == 2
    assert spend_column["type"] == "number"
    assert spend_column["summary_statistics"]["sum"] == 2000.5


def test_profile_csv_dataset_reports_missing_values(tmp_path):
    csv_path = tmp_path / "procurement_missing.csv"
    csv_path.write_text(
        "\n".join(
            [
                "supplier,category,spend_amount",
                "Acme,Software,1200.50",
                "Zenith,,800.00",
                ",Hardware,",
            ]
        ),
        encoding="utf-8",
    )

    profile = profile_csv_dataset(csv_path)
    quality = profile.quality_artifact()
    schema = profile.schema_artifact()
    category_column = next(column for column in schema["columns"] if column["name"] == "category")

    assert quality["missing_cells"] == 3
    assert set(quality["columns_with_missing"]) == {"supplier", "category", "spend_amount"}
    assert category_column["missing_count"] == 1
    assert category_column["nullable"] is True


def test_profile_csv_dataset_rejects_unsupported_file_type(tmp_path):
    json_path = tmp_path / "procurement.json"
    json_path.write_text("[]", encoding="utf-8")

    with pytest.raises(DataIngestionError) as exc_info:
        profile_csv_dataset(json_path)

    assert "Unsupported dataset file type" in str(exc_info.value)


def test_csv_dataset_adapter_supports_preview_and_grouped_sum(tmp_path):
    csv_path = tmp_path / "procurement.csv"
    write_procurement_csv(csv_path)

    adapter = CsvDatasetAdapter.from_path(csv_path)

    assert adapter.columns() == [
        "supplier",
        "category",
        "invoice_date",
        "spend_amount",
        "department",
    ]
    assert adapter.preview(limit=1)[0]["supplier"] == "Acme"
    assert adapter.aggregate_sum_by("supplier", "spend_amount") == {
        "Acme": 1500.5,
        "Zenith": 800.0,
    }


def test_data_retrieval_agent_registers_schema_and_quality_artifacts(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    csv_path = tmp_path / "procurement.csv"
    write_procurement_csv(csv_path)
    dataset_artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(csv_path),
        metadata={"source": "test", "format": "csv"},
    )
    agent = DataRetrievalAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="data_profile",
            task="Profile procurement dataset.",
            context={"dataset_artifact_id": dataset_artifact.id},
        )
    )

    artifacts = repository.list_artifacts(run.id)
    schema_artifact = repository.get_artifact(run.id, output.artifacts[0])
    quality_artifact = repository.get_artifact(run.id, output.artifacts[1])
    schema_payload = json.loads(
        (tmp_path / "artifacts" / run.id / "data_profile" / "schema_profile.json").read_text()
    )

    assert output.status == "succeeded"
    assert len(artifacts) == 3
    assert schema_artifact.type == ArtifactType.SCHEMA_PROFILE
    assert quality_artifact.type == ArtifactType.QUALITY_REPORT
    assert schema_artifact.source_artifact_ids == [dataset_artifact.id]
    assert quality_artifact.metadata["missing_cells"] == 0
    assert schema_payload["row_count"] == 3
    assert output.metrics["adapter"] == "CsvDatasetAdapter"


def test_data_retrieval_agent_fails_for_unsupported_dataset_artifact(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    bad_path = tmp_path / "procurement.json"
    bad_path.write_text("[]", encoding="utf-8")
    dataset_artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(bad_path),
        metadata={"source": "test", "format": "json"},
    )
    agent = DataRetrievalAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="data_profile",
            task="Profile procurement dataset.",
            context={"dataset_artifact_id": dataset_artifact.id},
        )
    )

    assert output.status == "failed"
    assert "Unsupported dataset file type" in output.errors[0]


def test_data_retrieval_agent_profiles_sqlite_warehouse_reference(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    db_path = tmp_path / "warehouse.db"
    write_procurement_sqlite(db_path)
    dataset_artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=f"sqlite://{db_path}#procurement",
        metadata={"source": "warehouse", "format": "sqlite"},
    )
    agent = DataRetrievalAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="data_profile",
            task="Profile procurement dataset.",
            context={"dataset_artifact_id": dataset_artifact.id},
        )
    )

    schema_artifact = repository.get_artifact(run.id, output.artifacts[0])
    quality_artifact = repository.get_artifact(run.id, output.artifacts[1])
    schema_payload = json.loads(
        (tmp_path / "artifacts" / run.id / "data_profile" / "schema_profile.json").read_text()
    )

    assert output.status == "succeeded"
    assert output.metrics["adapter"] == "SqliteWarehouseConnector"
    assert output.metrics["dataset_kind"] == "warehouse"
    assert output.metrics["preview"][0]["supplier"] == "Acme"
    assert schema_artifact.metadata["dataset_kind"] == "warehouse"
    assert quality_artifact.metadata["missing_cells"] == 0
    assert schema_payload["row_count"] == 3
    assert [column["name"] for column in schema_payload["columns"]] == [
        "supplier",
        "category",
        "invoice_date",
        "spend_amount",
        "department",
    ]


def test_data_retrieval_agent_fails_clearly_for_unconfigured_snowflake_reference(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    dataset_artifact = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri="snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
        metadata={"source": "warehouse"},
    )
    agent = DataRetrievalAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="data_profile",
            task="Profile procurement dataset.",
            context={"dataset_artifact_id": dataset_artifact.id},
        )
    )

    assert output.status == "failed"
    assert "Missing Snowflake connector configuration" in output.errors[0]

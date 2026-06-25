from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aeai_os.agents.base import AgentInput, AgentOutput
from aeai_os.data import (
    CsvDatasetAdapter,
    DataIngestionError,
    WarehouseConnectorRegistry,
    WarehouseDatasetAdapter,
    dataset_reference_from_metadata,
    default_warehouse_registry,
    profile_csv_dataset,
    profile_tabular_rows,
)
from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import AgentEventType, ArtifactType


class DataRetrievalAgent:
    agent_type = "data_retrieval"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        warehouse_registry: WarehouseConnectorRegistry | None = None,
        warehouse_profile_row_limit: int = 10_000,
    ) -> None:
        self._repository = repository
        self._artifact_root = Path(artifact_root)
        self._warehouse_registry = warehouse_registry or default_warehouse_registry()
        self._warehouse_profile_row_limit = warehouse_profile_row_limit

    def execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            dataset = self._resolve_dataset_artifact(agent_input)
            dataset_reference = dataset_reference_from_metadata(dataset.uri, dataset.metadata)
            if dataset_reference.kind == "warehouse":
                if dataset_reference.warehouse is None:
                    raise DataIngestionError(
                        "Warehouse dataset reference is missing source details."
                    )
                connector = self._warehouse_registry.connector_for_reference(
                    dataset_reference.warehouse
                )
                adapter = WarehouseDatasetAdapter(
                    connector=connector,
                    reference=dataset_reference.warehouse,
                    row_limit=self._warehouse_profile_row_limit,
                )
                profile = profile_tabular_rows(
                    source_path=dataset.uri,
                    rows=adapter.rows(),
                    fieldnames=adapter.columns(),
                )
                adapter_name = connector.__class__.__name__
                dataset_kind = "warehouse"
            else:
                profile = profile_csv_dataset(dataset.uri)
                adapter = CsvDatasetAdapter.from_path(dataset.uri)
                adapter_name = "CsvDatasetAdapter"
                dataset_kind = "local_file"

            output_dir = self._artifact_root / agent_input.run_id / agent_input.node_id
            output_dir.mkdir(parents=True, exist_ok=True)

            schema_path = output_dir / "schema_profile.json"
            quality_path = output_dir / "quality_report.json"
            _write_json(schema_path, profile.schema_artifact())
            _write_json(quality_path, profile.quality_artifact())

            schema_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.SCHEMA_PROFILE,
                uri=str(schema_path),
                metadata={
                    "source": "data_retrieval_agent",
                    "dataset_kind": dataset_kind,
                    "row_count": profile.row_count,
                    "column_count": profile.column_count,
                    "format": "json",
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )
            quality_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.QUALITY_REPORT,
                uri=str(quality_path),
                metadata={
                    "source": "data_retrieval_agent",
                    "dataset_kind": dataset_kind,
                    "missing_cells": profile.quality_summary["missing_cells"],
                    "duplicate_row_count": profile.quality_summary["duplicate_row_count"],
                    "format": "json",
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )

        except (DataIngestionError, KeyError, OSError) as exc:
            return AgentOutput(
                status="failed",
                summary="Data retrieval agent failed to ingest the dataset.",
                errors=[str(exc)],
                events=[
                    {
                        "event_type": AgentEventType.ERROR,
                        "message": str(exc),
                    }
                ],
            )

        return AgentOutput(
            status="succeeded",
            summary=(
                f"Profiled CSV dataset with {profile.row_count} rows and "
                f"{profile.column_count} columns."
            ),
            artifacts=[schema_artifact.id, quality_artifact.id],
            events=[
                {
                    "event_type": AgentEventType.LOG,
                    "message": "CSV dataset profiled and artifacts registered.",
                    "dataset_artifact_id": dataset.id,
                    "schema_artifact_id": schema_artifact.id,
                    "quality_artifact_id": quality_artifact.id,
                }
            ],
            metrics={
                "row_count": profile.row_count,
                "column_count": profile.column_count,
                "missing_cells": profile.quality_summary["missing_cells"],
                "columns": [column.name for column in profile.columns],
                "preview": adapter.preview(limit=3),
                "adapter": adapter_name,
                "dataset_kind": dataset_kind,
            },
        )

    def _resolve_dataset_artifact(self, agent_input: AgentInput) -> ArtifactRecord:
        artifact_id = (
            agent_input.context.get("dataset_artifact_id")
            or self._repository.get_run(agent_input.run_id).dataset_artifact_id
        )
        if artifact_id:
            artifact = self._repository.get_artifact(agent_input.run_id, artifact_id)
            if artifact.type != ArtifactType.DATASET:
                raise DataIngestionError(f"Artifact is not a dataset: {artifact_id}")
            return artifact

        dataset_uri = agent_input.context.get("dataset_uri")
        if not dataset_uri:
            raise DataIngestionError("No dataset artifact or dataset URI was provided.")

        return self._repository.add_artifact(
            run_id=agent_input.run_id,
            artifact_type=ArtifactType.DATASET,
            uri=str(dataset_uri),
            metadata={"source": "data_retrieval_agent", "format": "csv"},
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

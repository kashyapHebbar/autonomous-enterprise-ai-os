from __future__ import annotations

from pathlib import Path

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
from aeai_os.storage import ArtifactStorageError, ArtifactStore, LocalArtifactStore


class DataRetrievalAgent:
    agent_type = "data_retrieval"

    def __init__(
        self,
        repository: InMemoryRunRepository,
        artifact_root: str | Path,
        warehouse_registry: WarehouseConnectorRegistry | None = None,
        warehouse_profile_row_limit: int = 10_000,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._repository = repository
        self._artifact_store = artifact_store or LocalArtifactStore(artifact_root)
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
                dataset_path = self._artifact_store.local_path(dataset.uri)
                profile = profile_csv_dataset(dataset_path)
                adapter = CsvDatasetAdapter.from_path(dataset_path)
                adapter_name = "CsvDatasetAdapter"
                dataset_kind = (
                    "public_url" if dataset.uri.lower().startswith("https://") else "local_file"
                )

            schema_artifact_id = self._repository.next_artifact_id()
            quality_artifact_id = self._repository.next_artifact_id()
            schema_payload = self._artifact_store.write_json(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="schema_profile.json",
                payload=profile.schema_artifact(),
            )
            quality_payload = self._artifact_store.write_json(
                run_id=agent_input.run_id,
                node_id=agent_input.node_id,
                filename="quality_report.json",
                payload=profile.quality_artifact(),
            )

            schema_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.SCHEMA_PROFILE,
                artifact_id=schema_artifact_id,
                uri=schema_payload.uri,
                metadata={
                    "source": "data_retrieval_agent",
                    "dataset_kind": dataset_kind,
                    "row_count": profile.row_count,
                    "column_count": profile.column_count,
                    "format": "json",
                    **schema_payload.metadata,
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )
            quality_artifact = self._repository.add_artifact(
                run_id=agent_input.run_id,
                artifact_type=ArtifactType.QUALITY_REPORT,
                artifact_id=quality_artifact_id,
                uri=quality_payload.uri,
                metadata={
                    "source": "data_retrieval_agent",
                    "dataset_kind": dataset_kind,
                    "missing_cells": profile.quality_summary["missing_cells"],
                    "duplicate_row_count": profile.quality_summary["duplicate_row_count"],
                    "format": "json",
                    **quality_payload.metadata,
                },
                source_artifact_ids=[dataset.id],
                producer_node_id=agent_input.node_id,
            )

        except (ArtifactStorageError, DataIngestionError, KeyError, OSError) as exc:
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

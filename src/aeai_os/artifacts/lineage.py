from __future__ import annotations

from dataclasses import dataclass

from aeai_os.runs.models import ArtifactRecord
from aeai_os.runs.repository import InMemoryRunRepository


@dataclass(frozen=True)
class ArtifactLineageEdge:
    source_artifact_id: str
    target_artifact_id: str


@dataclass(frozen=True)
class ArtifactLineage:
    root_artifact: ArtifactRecord
    upstream_artifacts: list[ArtifactRecord]
    edges: list[ArtifactLineageEdge]


class ArtifactLineageService:
    def __init__(self, repository: InMemoryRunRepository) -> None:
        self._repository = repository

    def build_lineage(self, run_id: str, artifact_id: str) -> ArtifactLineage:
        root_artifact = self._repository.get_artifact(run_id, artifact_id)
        upstream_artifacts: dict[str, ArtifactRecord] = {}
        edges: list[ArtifactLineageEdge] = []
        visiting: set[str] = set()

        def visit(target: ArtifactRecord) -> None:
            if target.id in visiting:
                return
            visiting.add(target.id)
            for source_artifact_id in target.source_artifact_ids:
                edges.append(
                    ArtifactLineageEdge(
                        source_artifact_id=source_artifact_id,
                        target_artifact_id=target.id,
                    )
                )
                if source_artifact_id in upstream_artifacts:
                    continue
                source_artifact = self._repository.get_artifact(run_id, source_artifact_id)
                upstream_artifacts[source_artifact.id] = source_artifact
                visit(source_artifact)
            visiting.remove(target.id)

        visit(root_artifact)
        return ArtifactLineage(
            root_artifact=root_artifact,
            upstream_artifacts=list(upstream_artifacts.values()),
            edges=edges,
        )

    def expand_source_artifact_ids(self, run_id: str, artifact_ids: list[str]) -> list[str]:
        ordered_ids: list[str] = []
        seen: set[str] = set()

        def append_once(artifact_id: str) -> None:
            if artifact_id in seen:
                return
            seen.add(artifact_id)
            ordered_ids.append(artifact_id)

        for artifact_id in artifact_ids:
            self._repository.get_artifact(run_id, artifact_id)
            append_once(artifact_id)
            lineage = self.build_lineage(run_id, artifact_id)
            for upstream_artifact in lineage.upstream_artifacts:
                append_once(upstream_artifact.id)

        return ordered_ids

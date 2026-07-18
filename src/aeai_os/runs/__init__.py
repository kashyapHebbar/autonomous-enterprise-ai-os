"""Run lifecycle domain package."""

from aeai_os.runs.models import (
    AgentEventRecord,
    ArtifactRecord,
    EvaluationResultRecord,
    GraphNodeRecord,
    RunCheckpointRecord,
    RunRecord,
    WorkflowJobRecord,
)
from aeai_os.runs.repository import (
    ArtifactNotFoundError,
    EvaluationResultNotFoundError,
    GraphNodeNotFoundError,
    InMemoryRunRepository,
    RunCheckpointNotFoundError,
    RunNotFoundError,
    WorkflowJobNotFoundError,
    WorkflowJobOwnershipError,
    WorkflowJobStateError,
)


def __getattr__(name: str):
    if name != "SQLAlchemyRunRepository":
        raise AttributeError(f"module 'aeai_os.runs' has no attribute {name!r}")
    from aeai_os.runs.sqlalchemy_repository import SQLAlchemyRunRepository

    globals()[name] = SQLAlchemyRunRepository
    return SQLAlchemyRunRepository

__all__ = [
    "AgentEventRecord",
    "ArtifactNotFoundError",
    "ArtifactRecord",
    "EvaluationResultNotFoundError",
    "EvaluationResultRecord",
    "GraphNodeNotFoundError",
    "GraphNodeRecord",
    "InMemoryRunRepository",
    "RunCheckpointNotFoundError",
    "RunCheckpointRecord",
    "RunNotFoundError",
    "RunRecord",
    "SQLAlchemyRunRepository",
    "WorkflowJobNotFoundError",
    "WorkflowJobOwnershipError",
    "WorkflowJobRecord",
    "WorkflowJobStateError",
]

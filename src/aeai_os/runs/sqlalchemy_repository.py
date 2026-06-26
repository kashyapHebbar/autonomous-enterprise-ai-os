from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from aeai_os.observability.mlflow_tracking import log_evaluation_to_mlflow
from aeai_os.observability.tracing import ensure_trace_id, start_span
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
    RunCheckpointNotFoundError,
    RunNotFoundError,
    WorkflowJobNotFoundError,
    _evaluation_event,
    utc_now,
)
from aeai_os.schemas.enums import (
    ArtifactType,
    GraphNodeStatus,
    RunStatus,
    WorkflowJobStatus,
)
from aeai_os.storage.sqlalchemy_models import (
    AgentEventModel,
    ArtifactModel,
    Base,
    EvaluationResultModel,
    GraphNodeModel,
    RunCheckpointModel,
    RunModel,
    WorkflowJobModel,
)


class SQLAlchemyRunRepository:
    """Durable run repository backed by SQLAlchemy-compatible databases."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @classmethod
    def from_engine(
        cls,
        engine: Engine,
        *,
        create_schema: bool = False,
    ) -> SQLAlchemyRunRepository:
        if create_schema:
            Base.metadata.create_all(engine)
        return cls(sessionmaker(bind=engine, expire_on_commit=False))

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        create_schema: bool = False,
    ) -> SQLAlchemyRunRepository:
        return cls.from_engine(create_engine(database_url), create_schema=create_schema)

    def create_run(
        self,
        task: str,
        metadata: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> RunRecord:
        normalized_task = task.strip()
        if len(normalized_task) < 3:
            raise ValueError("Task must contain at least 3 non-whitespace characters.")

        now = utc_now()
        model = RunModel(
            id=f"run_{uuid4().hex}",
            task=normalized_task,
            status=RunStatus.PENDING.value,
            metadata_json=dict(metadata or {}),
            created_at=now,
            updated_at=now,
            trace_id=ensure_trace_id(trace_id),
        )
        with self._session_factory() as session:
            session.add(model)
            session.commit()
            return _run_from_model(model)

    def list_runs(self) -> list[RunRecord]:
        with self._session_factory() as session:
            models = session.scalars(select(RunModel).order_by(RunModel.created_at)).all()
            return [_run_from_model(model) for model in models]

    def get_run(self, run_id: str) -> RunRecord:
        with self._session_factory() as session:
            return _run_from_model(_get_run_model(session, run_id))

    def update_status(
        self,
        run_id: str,
        status: RunStatus,
        error_summary: str | None = None,
    ) -> RunRecord:
        with self._session_factory() as session:
            model = _get_run_model(session, run_id)
            model.status = status.value
            model.error_summary = error_summary
            model.updated_at = utc_now()
            session.commit()
            return _run_from_model(model)

    def enqueue_workflow_job(
        self,
        run_id: str,
        workflow_name: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        job_id: str | None = None,
    ) -> WorkflowJobRecord:
        normalized_workflow = workflow_name.strip()
        if not normalized_workflow:
            raise ValueError("Workflow name is required.")
        if max_attempts < 1:
            raise ValueError("Workflow job max_attempts must be at least 1.")

        with self._session_factory() as session:
            _get_run_model(session, run_id)
            now = utc_now()
            model = WorkflowJobModel(
                id=job_id or f"job_{uuid4().hex}",
                run_id=run_id,
                workflow_name=normalized_workflow,
                status=WorkflowJobStatus.QUEUED.value,
                payload=deepcopy(payload or {}),
                attempt_count=0,
                max_attempts=max_attempts,
                created_at=now,
                updated_at=now,
            )
            session.add(model)
            session.commit()
            return _workflow_job_from_model(model)

    def list_workflow_jobs(
        self,
        run_id: str | None = None,
        status: WorkflowJobStatus | None = None,
    ) -> list[WorkflowJobRecord]:
        with self._session_factory() as session:
            if run_id is not None:
                _get_run_model(session, run_id)
            query = select(WorkflowJobModel)
            if run_id is not None:
                query = query.where(WorkflowJobModel.run_id == run_id)
            if status is not None:
                query = query.where(WorkflowJobModel.status == status.value)
            models = session.scalars(query.order_by(WorkflowJobModel.created_at)).all()
            return [_workflow_job_from_model(model) for model in models]

    def get_workflow_job(self, job_id: str) -> WorkflowJobRecord:
        with self._session_factory() as session:
            return _workflow_job_from_model(_get_workflow_job_model(session, job_id))

    def claim_next_workflow_job(
        self,
        worker_id: str,
        workflow_name: str | None = None,
    ) -> WorkflowJobRecord | None:
        normalized_workflow = workflow_name.strip() if workflow_name else None
        with self._session_factory() as session:
            query = select(WorkflowJobModel).where(
                WorkflowJobModel.status == WorkflowJobStatus.QUEUED.value
            )
            if normalized_workflow is not None:
                query = query.where(WorkflowJobModel.workflow_name == normalized_workflow)
            model = session.scalars(query.order_by(WorkflowJobModel.created_at)).first()
            if model is None:
                return None

            now = utc_now()
            model.status = WorkflowJobStatus.RUNNING.value
            model.worker_id = worker_id
            model.attempt_count += 1
            model.started_at = model.started_at or now
            model.updated_at = now
            session.commit()
            return _workflow_job_from_model(model)

    def complete_workflow_job(self, job_id: str) -> WorkflowJobRecord:
        with self._session_factory() as session:
            model = _get_workflow_job_model(session, job_id)
            now = utc_now()
            model.status = WorkflowJobStatus.COMPLETED.value
            model.updated_at = now
            model.finished_at = now
            session.commit()
            return _workflow_job_from_model(model)

    def fail_workflow_job(
        self,
        job_id: str,
        error_summary: str,
        retry: bool = True,
    ) -> WorkflowJobRecord:
        with self._session_factory() as session:
            model = _get_workflow_job_model(session, job_id)
            now = utc_now()
            should_retry = retry and model.attempt_count < model.max_attempts
            model.status = (
                WorkflowJobStatus.QUEUED.value
                if should_retry
                else WorkflowJobStatus.FAILED.value
            )
            if should_retry:
                model.worker_id = None
                model.finished_at = None
            else:
                model.finished_at = now
            model.error_summary = error_summary
            model.updated_at = now
            session.commit()
            return _workflow_job_from_model(model)

    def next_artifact_id(self) -> str:
        return f"artifact_{uuid4().hex}"

    def add_artifact(
        self,
        run_id: str,
        artifact_type: ArtifactType,
        uri: str,
        metadata: dict[str, Any] | None = None,
        source_artifact_ids: list[str] | None = None,
        producer_node_id: str | None = None,
        artifact_id: str | None = None,
    ) -> ArtifactRecord:
        with self._session_factory() as session:
            run = _get_run_model(session, run_id)
            model = ArtifactModel(
                id=artifact_id or self.next_artifact_id(),
                run_id=run_id,
                producer_node_id=producer_node_id,
                type=artifact_type.value,
                uri=uri,
                metadata_json=dict(metadata or {}),
                source_artifact_ids=list(source_artifact_ids or []),
                created_at=utc_now(),
            )
            session.add(model)
            if artifact_type == ArtifactType.DATASET:
                run.dataset_artifact_id = model.id
                run.updated_at = utc_now()
            session.commit()
            return _artifact_from_model(model)

    def list_artifacts(self, run_id: str) -> list[ArtifactRecord]:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            models = session.scalars(
                select(ArtifactModel)
                .where(ArtifactModel.run_id == run_id)
                .order_by(ArtifactModel.created_at)
            ).all()
            return [_artifact_from_model(model) for model in models]

    def get_artifact(self, run_id: str, artifact_id: str) -> ArtifactRecord:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            model = session.get(ArtifactModel, artifact_id)
            if model is None or model.run_id != run_id:
                raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
            return _artifact_from_model(model)

    def add_graph_node(self, node: GraphNodeRecord) -> GraphNodeRecord:
        return self.upsert_graph_node(node)

    def upsert_graph_node(self, node: GraphNodeRecord) -> GraphNodeRecord:
        with self._session_factory() as session:
            _get_run_model(session, node.run_id)
            model = session.get(
                GraphNodeModel,
                {"id": node.id, "run_id": node.run_id},
            )
            if model is None:
                model = GraphNodeModel(
                    id=node.id,
                    run_id=node.run_id,
                    agent_type=node.agent_type,
                    status=node.status.value,
                    depends_on=list(node.depends_on),
                    required_tools=list(node.required_tools),
                    expected_artifacts=list(node.expected_artifacts),
                    retry_count=node.retry_count,
                    started_at=node.started_at,
                    finished_at=node.finished_at,
                    created_at=node.created_at,
                    updated_at=node.updated_at,
                )
                session.add(model)
            else:
                _update_graph_node_model(model, node)
            session.commit()
            return _graph_node_from_model(model)

    def get_graph_node(self, run_id: str, node_id: str) -> GraphNodeRecord:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            model = session.get(GraphNodeModel, {"id": node_id, "run_id": run_id})
            if model is None:
                raise GraphNodeNotFoundError(f"Graph node not found: {node_id}")
            return _graph_node_from_model(model)

    def list_graph_nodes(self, run_id: str) -> list[GraphNodeRecord]:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            models = session.scalars(
                select(GraphNodeModel)
                .where(GraphNodeModel.run_id == run_id)
                .order_by(GraphNodeModel.created_at)
            ).all()
            return [_graph_node_from_model(model) for model in models]

    def add_event(self, event: AgentEventRecord) -> AgentEventRecord:
        with self._session_factory() as session:
            _get_run_model(session, event.run_id)
            model = AgentEventModel(
                id=event.id,
                run_id=event.run_id,
                node_id=event.node_id,
                event_type=str(event.event_type),
                payload=deepcopy(event.payload),
                created_at=event.created_at,
            )
            session.add(model)
            session.commit()
            return _event_from_model(model)

    def list_events(self, run_id: str) -> list[AgentEventRecord]:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            models = session.scalars(
                select(AgentEventModel)
                .where(AgentEventModel.run_id == run_id)
                .order_by(AgentEventModel.created_at)
            ).all()
            return [_event_from_model(model) for model in models]

    def add_evaluation(self, evaluation: EvaluationResultRecord) -> EvaluationResultRecord:
        with self._session_factory() as session:
            run = _get_run_model(session, evaluation.run_id)
            run_record = _run_from_model(run)
            record = evaluation
            if record.created_at is None:
                record = replace(record, created_at=utc_now())
            with start_span(
                "evaluation.result",
                {
                    "run.id": record.run_id,
                    "run.trace_id": run_record.trace_id,
                    "evaluation.id": record.id,
                    "evaluation.score": record.score,
                    "evaluation.passed": record.passed,
                    "evaluation.check_count": len(record.checks),
                    "evaluation.target_artifact_id": record.target_artifact_id,
                },
            ):
                model = EvaluationResultModel(
                    id=record.id,
                    run_id=record.run_id,
                    target_artifact_id=record.target_artifact_id,
                    score=record.score,
                    passed=record.passed,
                    checks=deepcopy(record.checks),
                    created_at=record.created_at,
                )
                mlflow_result = log_evaluation_to_mlflow(
                    run=run_record,
                    evaluation=record,
                )
                event_record = _evaluation_event(
                    record=record,
                    trace_id=run_record.trace_id,
                    mlflow_status=mlflow_result.status,
                    mlflow_message=mlflow_result.message,
                )
                event = AgentEventModel(
                    id=event_record.id,
                    run_id=event_record.run_id,
                    node_id=event_record.node_id,
                    event_type=str(event_record.event_type),
                    payload=deepcopy(event_record.payload),
                    created_at=event_record.created_at,
                )
                session.add_all([model, event])
                session.commit()
                return _evaluation_from_model(model)

    def list_evaluations(self, run_id: str) -> list[EvaluationResultRecord]:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            models = session.scalars(
                select(EvaluationResultModel)
                .where(EvaluationResultModel.run_id == run_id)
                .order_by(EvaluationResultModel.created_at)
            ).all()
            return [_evaluation_from_model(model) for model in models]

    def get_evaluation(self, run_id: str, evaluation_id: str) -> EvaluationResultRecord:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            model = session.get(EvaluationResultModel, evaluation_id)
            if model is None or model.run_id != run_id:
                raise EvaluationResultNotFoundError(
                    f"Evaluation result not found: {evaluation_id}"
                )
            return _evaluation_from_model(model)

    def save_checkpoint(self, run_id: str, state: dict[str, Any]) -> RunCheckpointRecord:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            now = utc_now()
            model = session.get(RunCheckpointModel, run_id)
            if model is None:
                model = RunCheckpointModel(
                    run_id=run_id,
                    version=1,
                    state_json=deepcopy(state),
                    created_at=now,
                    updated_at=now,
                )
                session.add(model)
            else:
                model.version += 1
                model.state_json = deepcopy(state)
                model.updated_at = now
            session.commit()
            return _checkpoint_from_model(model)

    def get_checkpoint(self, run_id: str) -> RunCheckpointRecord:
        with self._session_factory() as session:
            _get_run_model(session, run_id)
            model = session.get(RunCheckpointModel, run_id)
            if model is None:
                raise RunCheckpointNotFoundError(f"Run checkpoint not found: {run_id}")
            return _checkpoint_from_model(model)


def _get_run_model(session: Session, run_id: str) -> RunModel:
    model = session.get(RunModel, run_id)
    if model is None:
        raise RunNotFoundError(f"Run not found: {run_id}")
    return model


def _get_workflow_job_model(session: Session, job_id: str) -> WorkflowJobModel:
    model = session.get(WorkflowJobModel, job_id)
    if model is None:
        raise WorkflowJobNotFoundError(f"Workflow job not found: {job_id}")
    return model


def _run_from_model(model: RunModel) -> RunRecord:
    return RunRecord(
        id=model.id,
        task=model.task,
        status=RunStatus(model.status),
        metadata=dict(model.metadata_json or {}),
        dataset_artifact_id=model.dataset_artifact_id,
        trace_id=model.trace_id,
        error_summary=model.error_summary,
        created_at=_utc_datetime(model.created_at),
        updated_at=_utc_datetime(model.updated_at),
    )


def _workflow_job_from_model(model: WorkflowJobModel) -> WorkflowJobRecord:
    return WorkflowJobRecord(
        id=model.id,
        run_id=model.run_id,
        workflow_name=model.workflow_name,
        status=WorkflowJobStatus(model.status),
        payload=deepcopy(model.payload or {}),
        attempt_count=model.attempt_count,
        max_attempts=model.max_attempts,
        worker_id=model.worker_id,
        error_summary=model.error_summary,
        started_at=_optional_utc_datetime(model.started_at),
        finished_at=_optional_utc_datetime(model.finished_at),
        created_at=_utc_datetime(model.created_at),
        updated_at=_utc_datetime(model.updated_at),
    )


def _artifact_from_model(model: ArtifactModel) -> ArtifactRecord:
    return ArtifactRecord(
        id=model.id,
        run_id=model.run_id,
        producer_node_id=model.producer_node_id,
        type=ArtifactType(model.type),
        uri=model.uri,
        metadata=dict(model.metadata_json or {}),
        source_artifact_ids=list(model.source_artifact_ids or []),
        created_at=_utc_datetime(model.created_at),
    )


def _graph_node_from_model(model: GraphNodeModel) -> GraphNodeRecord:
    return GraphNodeRecord(
        id=model.id,
        run_id=model.run_id,
        agent_type=model.agent_type,
        status=GraphNodeStatus(model.status),
        depends_on=list(model.depends_on or []),
        required_tools=list(model.required_tools or []),
        expected_artifacts=list(model.expected_artifacts or []),
        retry_count=model.retry_count,
        started_at=_optional_utc_datetime(model.started_at),
        finished_at=_optional_utc_datetime(model.finished_at),
        created_at=_utc_datetime(model.created_at),
        updated_at=_utc_datetime(model.updated_at),
    )


def _update_graph_node_model(model: GraphNodeModel, node: GraphNodeRecord) -> None:
    model.agent_type = node.agent_type
    model.status = node.status.value
    model.depends_on = list(node.depends_on)
    model.required_tools = list(node.required_tools)
    model.expected_artifacts = list(node.expected_artifacts)
    model.retry_count = node.retry_count
    model.started_at = node.started_at
    model.finished_at = node.finished_at
    model.updated_at = node.updated_at


def _event_from_model(model: AgentEventModel) -> AgentEventRecord:
    return AgentEventRecord(
        id=model.id,
        run_id=model.run_id,
        node_id=model.node_id,
        event_type=model.event_type,
        payload=dict(model.payload or {}),
        created_at=_utc_datetime(model.created_at),
    )


def _evaluation_from_model(model: EvaluationResultModel) -> EvaluationResultRecord:
    return EvaluationResultRecord(
        id=model.id,
        run_id=model.run_id,
        target_artifact_id=model.target_artifact_id,
        score=model.score,
        passed=model.passed,
        checks=list(model.checks or []),
        created_at=_utc_datetime(model.created_at),
    )


def _checkpoint_from_model(model: RunCheckpointModel) -> RunCheckpointRecord:
    return RunCheckpointRecord(
        run_id=model.run_id,
        state=deepcopy(model.state_json or {}),
        version=model.version,
        created_at=_utc_datetime(model.created_at),
        updated_at=_utc_datetime(model.updated_at),
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _utc_datetime(value)

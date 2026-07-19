from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from aeai_os.api.auth import RunReader, RunWriter
from aeai_os.runs.models import AgentEventRecord, RunRecord
from aeai_os.runs.repository import InMemoryRunRepository, RunNotFoundError, utc_now
from aeai_os.schemas.enums import AgentEventType, ArtifactType
from aeai_os.security.auth import AuthenticatedUser
from aeai_os.storage import ArtifactStorageError, ArtifactStore

InvestigationStatus = Literal["new", "investigating", "confirmed", "dismissed", "resolved"]


class InvestigationHistoryResponse(BaseModel):
    status: InvestigationStatus
    assignee: str | None
    comment: str | None
    disposition_reason: str | None
    actor: dict[str, Any]
    created_at: datetime


class InvestigationResponse(BaseModel):
    id: str
    run_id: str
    run_task: str
    anomaly_id: str
    status: InvestigationStatus
    assignee: str | None
    supplier: str
    category: str
    amount: float
    currency: str
    risk_score: int
    severity: str
    confidence: float
    reason: str
    signals: list[dict[str, Any]]
    recommended_action: str
    row_number: int | None
    created_at: datetime
    updated_at: datetime
    history: list[InvestigationHistoryResponse] = Field(default_factory=list)


class InvestigationSummaryResponse(BaseModel):
    total: int
    new: int
    investigating: int
    confirmed: int
    dismissed: int
    resolved: int
    critical: int
    high: int
    risk_exposure: float
    risk_exposure_by_currency: dict[str, float]


class UpdateInvestigationRequest(BaseModel):
    status: InvestigationStatus | None = None
    assignee: str | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=2000)
    disposition_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_update(self):
        for name in ("assignee", "comment", "disposition_reason"):
            value = getattr(self, name)
            if value is not None:
                setattr(self, name, value.strip() or None)
        values = (self.status, self.assignee, self.comment, self.disposition_reason)
        if not any(value is not None for value in values):
            raise ValueError("At least one investigation field must be updated.")
        if self.status in {"confirmed", "dismissed"} and not (
            self.comment or self.disposition_reason
        ):
            raise ValueError("Confirmed or dismissed investigations require a rationale.")
        return self


def build_investigations_router(
    repository: InMemoryRunRepository, artifact_store: ArtifactStore
) -> APIRouter:
    router = APIRouter(prefix="/investigations", tags=["investigations"])

    @router.get("", response_model=list[InvestigationResponse])
    def list_investigations(
        user: RunReader,
        case_status: Annotated[InvestigationStatus | None, Query(alias="status")] = None,
        severity: Annotated[str | None, Query(max_length=20)] = None,
        search: Annotated[str | None, Query(max_length=200)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[InvestigationResponse]:
        cases = _tenant_cases(repository, artifact_store, user)
        if case_status:
            cases = [case for case in cases if case.status == case_status]
        if severity:
            cases = [case for case in cases if case.severity == severity.strip().lower()]
        if search and search.strip():
            query = search.strip().lower()
            cases = [case for case in cases if query in _case_search_text(case)]
        return cases[:limit]

    @router.get("/summary", response_model=InvestigationSummaryResponse)
    def investigation_summary(user: RunReader) -> InvestigationSummaryResponse:
        cases = _tenant_cases(repository, artifact_store, user)
        exposure_by_currency: dict[str, float] = defaultdict(float)
        for case in cases:
            if case.status != "dismissed":
                exposure_by_currency[case.currency] += case.amount
        return InvestigationSummaryResponse(
            total=len(cases),
            new=sum(case.status == "new" for case in cases),
            investigating=sum(case.status == "investigating" for case in cases),
            confirmed=sum(case.status == "confirmed" for case in cases),
            dismissed=sum(case.status == "dismissed" for case in cases),
            resolved=sum(case.status == "resolved" for case in cases),
            critical=sum(case.severity == "critical" for case in cases),
            high=sum(case.severity == "high" for case in cases),
            risk_exposure=round(
                sum(case.amount for case in cases if case.status != "dismissed"), 4
            ),
            risk_exposure_by_currency={
                currency: round(amount, 4)
                for currency, amount in sorted(exposure_by_currency.items())
            },
        )

    @router.get("/{run_id}/{anomaly_id}", response_model=InvestigationResponse)
    def get_investigation(run_id: str, anomaly_id: str, user: RunReader) -> InvestigationResponse:
        return _get_case_or_404(repository, artifact_store, run_id, anomaly_id, user)

    @router.patch("/{run_id}/{anomaly_id}", response_model=InvestigationResponse)
    def update_investigation(
        run_id: str,
        anomaly_id: str,
        request: Annotated[UpdateInvestigationRequest, Body(...)],
        actor: RunWriter,
    ) -> InvestigationResponse:
        current = _get_case_or_404(repository, artifact_store, run_id, anomaly_id, actor)
        repository.add_event(
            AgentEventRecord(
                id=f"event_{uuid4().hex}",
                run_id=run_id,
                node_id="investigations",
                event_type=AgentEventType.AUDIT.value,
                payload={
                    "message": f"{actor.id} updated investigation {anomaly_id}.",
                    "audit": True,
                    "action": "investigation.update",
                    "run_id": run_id,
                    "anomaly_id": anomaly_id,
                    "status": request.status or current.status,
                    "assignee": (
                        request.assignee if request.assignee is not None else current.assignee
                    ),
                    "comment": request.comment,
                    "disposition_reason": request.disposition_reason,
                    "actor": actor.to_audit_payload(),
                },
                created_at=utc_now(),
            )
        )
        return _get_case_or_404(repository, artifact_store, run_id, anomaly_id, actor)

    return router


def _tenant_cases(
    repository: InMemoryRunRepository,
    artifact_store: ArtifactStore,
    user: AuthenticatedUser,
) -> list[InvestigationResponse]:
    cases: list[InvestigationResponse] = []
    for run in repository.list_runs():
        if _visible(run, user):
            cases.extend(_run_cases(repository, artifact_store, run))
    return sorted(cases, key=lambda case: (-case.risk_score, -case.amount, case.id))


def _run_cases(
    repository: InMemoryRunRepository, artifact_store: ArtifactStore, run: RunRecord
) -> list[InvestigationResponse]:
    artifacts = [
        item for item in repository.list_artifacts(run.id) if item.type == ArtifactType.KPI_TABLE
    ]
    if not artifacts:
        return []
    try:
        analysis = artifact_store.read_json(artifacts[-1].uri)
    except (ArtifactStorageError, OSError, ValueError):
        return []
    histories = _histories(repository.list_events(run.id))
    return [
        _build_case(
            run,
            anomaly,
            histories.get(str(anomaly.get("id")), []),
            str(analysis.get("dataset", {}).get("currency") or "USD"),
        )
        for anomaly in analysis.get("anomalies", [])
        if anomaly.get("id")
    ]


def _build_case(
    run: RunRecord,
    anomaly: dict[str, Any],
    history: list[InvestigationHistoryResponse],
    currency: str,
) -> InvestigationResponse:
    latest = history[-1] if history else None
    return InvestigationResponse(
        id=f"{run.id}:{anomaly['id']}",
        run_id=run.id,
        run_task=run.task,
        anomaly_id=str(anomaly["id"]),
        status=latest.status if latest else "new",
        assignee=latest.assignee if latest else None,
        supplier=str(anomaly.get("supplier") or "<missing>"),
        category=str(anomaly.get("category") or "<missing>"),
        amount=float(anomaly.get("amount") or 0),
        currency=currency,
        risk_score=int(anomaly.get("risk_score") or 0),
        severity=str(anomaly.get("severity") or "low"),
        confidence=float(anomaly.get("confidence") or 0),
        reason=str(anomaly.get("reason") or "Review required."),
        signals=list(anomaly.get("signals") or []),
        recommended_action=str(anomaly.get("recommended_action") or "Review transaction."),
        row_number=anomaly.get("row_number"),
        created_at=run.created_at,
        updated_at=latest.created_at if latest else run.updated_at,
        history=history,
    )


def _histories(
    events: list[AgentEventRecord],
) -> dict[str, list[InvestigationHistoryResponse]]:
    result: dict[str, list[InvestigationHistoryResponse]] = {}
    for event in events:
        payload = event.payload
        if payload.get("action") != "investigation.update" or not payload.get("anomaly_id"):
            continue
        result.setdefault(str(payload["anomaly_id"]), []).append(
            InvestigationHistoryResponse(
                status=payload.get("status", "new"),
                assignee=payload.get("assignee"),
                comment=payload.get("comment"),
                disposition_reason=payload.get("disposition_reason"),
                actor=dict(payload.get("actor") or {}),
                created_at=event.created_at,
            )
        )
    return result


def _get_case_or_404(
    repository: InMemoryRunRepository,
    artifact_store: ArtifactStore,
    run_id: str,
    anomaly_id: str,
    user: AuthenticatedUser,
) -> InvestigationResponse:
    try:
        run = repository.get_run(run_id)
    except RunNotFoundError as exc:
        raise _not_found() from exc
    if not _visible(run, user):
        raise _not_found()
    for case in _run_cases(repository, artifact_store, run):
        if case.anomaly_id == anomaly_id:
            return case
    raise _not_found()


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investigation not found.")


def _visible(run: RunRecord, user: AuthenticatedUser) -> bool:
    return user.can_access(
        run.metadata.get("organization_id", "local-org"),
        run.metadata.get("workspace_id", "default"),
    )


def _case_search_text(case: InvestigationResponse) -> str:
    return " ".join(
        (case.supplier, case.category, case.reason, case.run_task, case.assignee or "")
    ).lower()

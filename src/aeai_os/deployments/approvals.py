from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aeai_os.runs.models import AgentEventRecord, ArtifactRecord, WorkflowJobRecord
from aeai_os.runs.repository import InMemoryRunRepository, utc_now
from aeai_os.schemas.enums import AgentEventType, ArtifactType, RunStatus, WorkflowJobStatus
from aeai_os.security import (
    PolicyEvaluationContext,
    ToolPermissionRegistry,
    ToolPolicyDecision,
    ToolPolicyDecisionStatus,
    default_tool_permission_registry,
)

DEPLOYMENT_WORKFLOW_NAME = "deployment"
DEPLOYMENT_NODE_ID = "deployment"


class DeploymentApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class DeploymentDecisionResult:
    job: WorkflowJobRecord
    deployment_artifact: ArtifactRecord | None = None


def request_deployment_approval(
    repository: InMemoryRunRepository,
    *,
    run_id: str,
    artifact_ids: Sequence[str],
    destination: str,
    requested_by: str | None = None,
    rationale: str | None = None,
    metadata: dict[str, Any] | None = None,
    policy_registry: ToolPermissionRegistry | None = None,
) -> WorkflowJobRecord:
    run = repository.get_run(run_id)
    if run.status == RunStatus.FAILED:
        raise DeploymentApprovalError("Cannot request deployment approval for a failed run.")

    normalized_artifact_ids = _validate_artifact_ids(repository, run_id, artifact_ids)
    normalized_destination = _normalize_required(destination, "Deployment destination is required.")
    policy_decision = _evaluate_deployment_policy(
        repository=repository,
        run_id=run_id,
        artifact_ids=normalized_artifact_ids,
        destination=normalized_destination,
        requested_by=requested_by,
        policy_registry=policy_registry or default_tool_permission_registry(),
    )
    if policy_decision.decision == ToolPolicyDecisionStatus.BLOCK:
        raise DeploymentApprovalError(policy_decision.reason)
    now = utc_now()
    payload = {
        "workflow": DEPLOYMENT_WORKFLOW_NAME,
        "request_type": "deployment_approval",
        "deployment_status": WorkflowJobStatus.WAITING_FOR_APPROVAL.value,
        "artifact_ids": normalized_artifact_ids,
        "destination": normalized_destination,
        "requested_by": _normalize_optional(requested_by) or "system",
        "request_rationale": _normalize_optional(rationale),
        "requested_at": now.isoformat(),
        "metadata": deepcopy(metadata or {}),
        "policy_decision": policy_decision.model_dump(mode="json"),
    }
    job = repository.enqueue_workflow_job(
        run_id=run_id,
        workflow_name=DEPLOYMENT_WORKFLOW_NAME,
        payload=payload,
        max_attempts=1,
        status=WorkflowJobStatus.WAITING_FOR_APPROVAL,
    )
    repository.update_status(run_id, RunStatus.WAITING_FOR_APPROVAL)
    repository.add_event(
        AgentEventRecord(
            id=f"event_{uuid4().hex}",
            run_id=run_id,
            node_id=DEPLOYMENT_NODE_ID,
            event_type=AgentEventType.APPROVAL_REQUEST.value,
            payload={
                "message": "Deployment approval requested.",
                "workflow_job_id": job.id,
                "deployment_job_id": job.id,
                "artifact_ids": normalized_artifact_ids,
                "destination": normalized_destination,
                "requested_by": payload["requested_by"],
                "rationale": payload["request_rationale"],
                "decision": "pending",
                "policy_decision": policy_decision.model_dump(mode="json"),
                "policy_rule_id": policy_decision.policy_rule_id,
                "escalation_target": policy_decision.escalation_target,
                "timestamp": now.isoformat(),
            },
            created_at=now,
        )
    )
    return job


def decide_deployment_approval(
    repository: InMemoryRunRepository,
    *,
    run_id: str,
    job_id: str,
    approved: bool,
    approver: str,
    rationale: str | None = None,
) -> DeploymentDecisionResult:
    repository.get_run(run_id)
    job = repository.get_workflow_job(job_id)
    _assert_deployment_job(job, run_id)
    if job.status != WorkflowJobStatus.WAITING_FOR_APPROVAL:
        raise DeploymentApprovalError(f"Deployment job is not waiting for approval: {job_id}")

    now = utc_now()
    decision = "approved" if approved else "denied"
    normalized_approver = _normalize_required(approver, "Deployment approver is required.")
    normalized_rationale = _normalize_optional(rationale)
    payload = deepcopy(job.payload)
    payload["deployment_status"] = decision
    payload["approval"] = {
        "decision": decision,
        "approved": approved,
        "approver": normalized_approver,
        "rationale": normalized_rationale,
        "decided_at": now.isoformat(),
    }

    deployment_artifact: ArtifactRecord | None = None
    error_summary = None
    if approved:
        deployment_artifact = repository.add_artifact(
            run_id=run_id,
            artifact_type=ArtifactType.DEPLOYMENT,
            uri=f"deployment://{payload['destination']}/{job.id}",
            metadata={
                "workflow_job_id": job.id,
                "deployment_status": decision,
                "destination": payload["destination"],
                "artifact_ids": list(payload["artifact_ids"]),
                "requested_by": payload.get("requested_by"),
                "request_rationale": payload.get("request_rationale"),
                "approved_by": normalized_approver,
                "approval_rationale": normalized_rationale,
                "approved_at": now.isoformat(),
                "metadata": deepcopy(payload.get("metadata") or {}),
            },
            source_artifact_ids=list(payload["artifact_ids"]),
            producer_node_id=DEPLOYMENT_NODE_ID,
        )
        payload["deployment_artifact_id"] = deployment_artifact.id
        result_status = WorkflowJobStatus.COMPLETED
        repository.update_status(run_id, RunStatus.COMPLETED)
    else:
        error_summary = "Deployment approval denied."
        result_status = WorkflowJobStatus.FAILED
        repository.update_status(run_id, RunStatus.FAILED, error_summary=error_summary)

    updated_job = repository.update_workflow_job_result(
        job.id,
        status=result_status,
        payload=payload,
        error_summary=error_summary,
    )
    repository.add_event(
        AgentEventRecord(
            id=f"event_{uuid4().hex}",
            run_id=run_id,
            node_id=DEPLOYMENT_NODE_ID,
            event_type=AgentEventType.APPROVAL_DECISION.value,
            payload={
                "message": f"Deployment {decision}.",
                "workflow_job_id": job.id,
                "deployment_job_id": job.id,
                "deployment_artifact_id": deployment_artifact.id if deployment_artifact else None,
                "artifact_ids": list(payload["artifact_ids"]),
                "destination": payload["destination"],
                "decision": decision,
                "approved": approved,
                "approver": normalized_approver,
                "rationale": normalized_rationale,
                "timestamp": now.isoformat(),
            },
            created_at=now,
        )
    )
    return DeploymentDecisionResult(job=updated_job, deployment_artifact=deployment_artifact)


def _assert_deployment_job(job: WorkflowJobRecord, run_id: str) -> None:
    if job.run_id != run_id:
        raise DeploymentApprovalError(f"Deployment job not found for run: {job.id}")
    if job.workflow_name != DEPLOYMENT_WORKFLOW_NAME:
        raise DeploymentApprovalError(f"Workflow job is not a deployment request: {job.id}")
    if job.payload.get("request_type") != "deployment_approval":
        raise DeploymentApprovalError(
            f"Workflow job is missing deployment approval payload: {job.id}"
        )


def _validate_artifact_ids(
    repository: InMemoryRunRepository,
    run_id: str,
    artifact_ids: Sequence[str],
) -> list[str]:
    normalized_artifact_ids: list[str] = []
    seen: set[str] = set()
    for artifact_id in artifact_ids:
        normalized = str(artifact_id).strip()
        if not normalized or normalized in seen:
            continue
        repository.get_artifact(run_id, normalized)
        normalized_artifact_ids.append(normalized)
        seen.add(normalized)
    if not normalized_artifact_ids:
        raise DeploymentApprovalError("At least one artifact is required for deployment.")
    return normalized_artifact_ids


def _evaluate_deployment_policy(
    *,
    repository: InMemoryRunRepository,
    run_id: str,
    artifact_ids: Sequence[str],
    destination: str,
    requested_by: str | None,
    policy_registry: ToolPermissionRegistry,
) -> ToolPolicyDecision:
    artifacts = [repository.get_artifact(run_id, artifact_id) for artifact_id in artifact_ids]
    metadata = {
        "artifact_ids": list(artifact_ids),
        "artifact_types": [artifact.type.value for artifact in artifacts],
        "requested_by": _normalize_optional(requested_by) or "system",
        "sensitive": any(_artifact_is_sensitive(artifact) for artifact in artifacts),
    }
    input_summary = (
        f"deploy {len(artifact_ids)} artifact(s) to {destination}; "
        f"requested_by={metadata['requested_by']}"
    )
    return policy_registry.evaluate(
        "deploy_artifact",
        input_summary=input_summary,
        context=PolicyEvaluationContext(
            input_summary=input_summary,
            run_id=run_id,
            destination=destination,
            artifact_type=",".join(sorted(set(metadata["artifact_types"]))),
            artifact_sensitive=bool(metadata["sensitive"]),
            metadata=metadata,
        ),
    )


def _artifact_is_sensitive(artifact: ArtifactRecord) -> bool:
    metadata = artifact.metadata
    for key in ("sensitive", "pii", "contains_pii", "secret", "credential_profile_id"):
        value = metadata.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes"}:
            return True
    return False


def _normalize_required(value: str, message: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise DeploymentApprovalError(message)
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

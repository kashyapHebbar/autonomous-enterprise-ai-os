from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING

from aeai_os.schemas.enums import ArtifactType, RunStatus, WorkflowJobStatus

if TYPE_CHECKING:
    from aeai_os.runs.models import GraphNodeRecord, RunRecord, WorkflowJobRecord
    from aeai_os.runs.repository import InMemoryRunRepository

RUN_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1800)
WORKFLOW_JOB_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600)
AGENT_NODE_DURATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120)


def render_prometheus_metrics(repository: InMemoryRunRepository) -> str:
    runs = repository.list_runs()
    status_counts = Counter(run.status.value for run in runs)
    workflow_job_counts: Counter[tuple[str, str]] = Counter()
    total_artifacts = 0
    total_evaluations = 0
    evaluation_passed_total = 0
    evaluation_failed_total = 0
    evaluation_scores: list[float] = []
    artifact_counts: Counter[str] = Counter()
    node_counts: dict[tuple[str, str], int] = defaultdict(int)
    node_durations: dict[str, list[float]] = defaultdict(list)
    node_retries_total = 0
    error_events_total = 0
    workflow_job_attempts_total = 0
    workflow_job_durations: dict[str, list[float]] = defaultdict(list)

    for run in runs:
        artifacts = repository.list_artifacts(run.id)
        total_artifacts += len(artifacts)
        artifact_counts.update(artifact.type.value for artifact in artifacts)
        evaluations = repository.list_evaluations(run.id)
        total_evaluations += len(evaluations)
        evaluation_scores.extend(evaluation.score for evaluation in evaluations)
        evaluation_passed_total += sum(1 for evaluation in evaluations if evaluation.passed)
        evaluation_failed_total += sum(1 for evaluation in evaluations if not evaluation.passed)
        error_events_total += sum(
            1 for event in repository.list_events(run.id) if event.event_type == "error"
        )
        for node in repository.list_graph_nodes(run.id):
            node_counts[(node.agent_type, node.status.value)] += 1
            node_retries_total += node.retry_count
            if duration := _node_duration_seconds(node):
                node_durations[node.agent_type].append(duration)
        for job in repository.list_workflow_jobs(run_id=run.id):
            workflow_job_counts[(job.workflow_name, job.status.value)] += 1
            workflow_job_attempts_total += job.attempt_count
            if duration := _workflow_job_duration_seconds(job):
                workflow_job_durations[job.workflow_name].append(duration)

    failed_runs_total = status_counts[RunStatus.FAILED.value]
    run_durations = [_run_duration_seconds(run) for run in runs]
    run_duration_seconds_sum = sum(run_durations)
    average_evaluation_score = (
        sum(evaluation_scores) / len(evaluation_scores) if evaluation_scores else 0.0
    )
    latest_evaluation_score = evaluation_scores[-1] if evaluation_scores else 0.0

    lines = [
        "# HELP aeai_runs_total Total number of runs tracked by the service.",
        "# TYPE aeai_runs_total gauge",
        f"aeai_runs_total {len(runs)}",
        "# HELP aeai_runs_by_status Number of runs by lifecycle status.",
        "# TYPE aeai_runs_by_status gauge",
    ]
    for status in RunStatus:
        lines.append(
            f'aeai_runs_by_status{{status="{_escape_label(status.value)}"}} '
            f"{status_counts[status.value]}"
        )

    lines.extend(
        [
            "# HELP aeai_run_errors_total Failed runs plus explicit agent error events.",
            "# TYPE aeai_run_errors_total counter",
            f"aeai_run_errors_total {failed_runs_total + error_events_total}",
            "# HELP aeai_artifacts_total Total artifacts produced or attached to runs.",
            "# TYPE aeai_artifacts_total gauge",
            f"aeai_artifacts_total {total_artifacts}",
            "# HELP aeai_artifacts_by_type Artifacts produced or attached by artifact type.",
            "# TYPE aeai_artifacts_by_type gauge",
        ]
    )
    for artifact_type in ArtifactType:
        lines.append(
            f'aeai_artifacts_by_type{{type="{_escape_label(artifact_type.value)}"}} '
            f"{artifact_counts[artifact_type.value]}"
        )

    lines.extend(
        [
            "# HELP aeai_evaluations_total Total evaluation records stored for runs.",
            "# TYPE aeai_evaluations_total gauge",
            f"aeai_evaluations_total {total_evaluations}",
            "# HELP aeai_evaluations_by_result Evaluation records by pass/fail result.",
            "# TYPE aeai_evaluations_by_result gauge",
            f'aeai_evaluations_by_result{{result="passed"}} {evaluation_passed_total}',
            f'aeai_evaluations_by_result{{result="failed"}} {evaluation_failed_total}',
            "# HELP aeai_evaluation_score_average Average score across stored evaluations.",
            "# TYPE aeai_evaluation_score_average gauge",
            f"aeai_evaluation_score_average {average_evaluation_score:.6f}",
            "# HELP aeai_evaluation_score Observed evaluation scores.",
            "# TYPE aeai_evaluation_score gauge",
            f"aeai_evaluation_score {latest_evaluation_score:.6f}",
            "# HELP aeai_node_retries_total Total graph node retry attempts.",
            "# TYPE aeai_node_retries_total counter",
            f"aeai_node_retries_total {node_retries_total}",
            "# HELP aeai_run_duration_seconds_sum Sum of observed run lifecycle durations.",
            "# TYPE aeai_run_duration_seconds_sum counter",
            f"aeai_run_duration_seconds_sum {run_duration_seconds_sum:.6f}",
            "# HELP aeai_run_duration_seconds_count Number of run durations observed.",
            "# TYPE aeai_run_duration_seconds_count counter",
            f"aeai_run_duration_seconds_count {len(runs)}",
            "# HELP aeai_agent_node_executions_total Graph nodes by agent and current status.",
            "# TYPE aeai_agent_node_executions_total gauge",
        ]
    )

    for (agent, status), count in sorted(node_counts.items()):
        lines.append(
            'aeai_agent_node_executions_total{'
            f'agent="{_escape_label(agent)}",status="{_escape_label(status)}"'
            f"}} {count}"
        )

    lines.extend(
        _histogram_lines(
            name="aeai_run_duration_seconds",
            help_text="Observed run lifecycle durations.",
            buckets=RUN_DURATION_BUCKETS,
            observations=run_durations,
        )
    )
    lines.extend(
        [
            "# HELP aeai_workflow_jobs_total Workflow jobs by workflow and status.",
            "# TYPE aeai_workflow_jobs_total gauge",
        ]
    )
    for workflow_name, status in _workflow_label_pairs(workflow_job_counts):
        lines.append(
            "aeai_workflow_jobs_total{"
            f'workflow="{_escape_label(workflow_name)}",status="{_escape_label(status)}"'
            f"}} {workflow_job_counts[(workflow_name, status)]}"
        )
    lines.extend(
        [
            "# HELP aeai_workflow_job_attempts_total Total workflow job attempts.",
            "# TYPE aeai_workflow_job_attempts_total counter",
            f"aeai_workflow_job_attempts_total {workflow_job_attempts_total}",
        ]
    )
    for workflow_name in sorted(workflow_job_durations):
        lines.extend(
            _histogram_lines(
                name="aeai_workflow_job_duration_seconds",
                help_text="Observed workflow job processing durations.",
                buckets=WORKFLOW_JOB_DURATION_BUCKETS,
                observations=workflow_job_durations[workflow_name],
                labels={"workflow": workflow_name},
                include_help=workflow_name == sorted(workflow_job_durations)[0],
            )
        )
    for agent_type in sorted(node_durations):
        lines.extend(
            _histogram_lines(
                name="aeai_agent_node_duration_seconds",
                help_text="Observed graph node execution durations by agent.",
                buckets=AGENT_NODE_DURATION_BUCKETS,
                observations=node_durations[agent_type],
                labels={"agent": agent_type},
                include_help=agent_type == sorted(node_durations)[0],
            )
        )

    return "\n".join(lines) + "\n"


def _run_duration_seconds(run: RunRecord) -> float:
    return max((run.updated_at - run.created_at).total_seconds(), 0.0)


def _workflow_job_duration_seconds(job: WorkflowJobRecord) -> float | None:
    start = job.started_at or job.created_at
    end = job.finished_at or job.updated_at
    return _duration_seconds(start, end)


def _node_duration_seconds(node: GraphNodeRecord) -> float | None:
    if node.started_at is None:
        return None
    return _duration_seconds(node.started_at, node.finished_at or node.updated_at)


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max((end - start).total_seconds(), 0.0)


def _workflow_label_pairs(
    counts: Counter[tuple[str, str]],
) -> list[tuple[str, str]]:
    pairs = set(counts)
    for status in WorkflowJobStatus:
        pairs.add(("procurement", status.value))
    return sorted(pairs)


def _histogram_lines(
    *,
    name: str,
    help_text: str,
    buckets: Iterable[float],
    observations: list[float],
    labels: dict[str, str] | None = None,
    include_help: bool = True,
) -> list[str]:
    lines: list[str] = []
    if include_help:
        lines.extend(
            [
                f"# HELP {name} {help_text}",
                f"# TYPE {name} histogram",
            ]
        )
    sorted_buckets = sorted(float(bucket) for bucket in buckets)
    for bucket in sorted_buckets:
        count = sum(1 for value in observations if value <= bucket)
        lines.append(
            f'{name}_bucket{_label_suffix(labels, {"le": _format_number(bucket)})} {count}'
        )
    lines.append(f'{name}_bucket{_label_suffix(labels, {"le": "+Inf"})} {len(observations)}')
    lines.append(f"{name}_sum{_label_suffix(labels)} {sum(observations):.6f}")
    lines.append(f"{name}_count{_label_suffix(labels)} {len(observations)}")
    return lines


def _label_suffix(
    labels: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    merged = {**(labels or {}), **(extra or {})}
    if not merged:
        return ""
    items = ",".join(
        f'{key}="{_escape_label(value)}"'
        for key, value in sorted(merged.items())
    )
    return "{" + items + "}"


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

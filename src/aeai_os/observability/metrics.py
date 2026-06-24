from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from aeai_os.schemas.enums import RunStatus

if TYPE_CHECKING:
    from aeai_os.runs.repository import InMemoryRunRepository


def render_prometheus_metrics(repository: InMemoryRunRepository) -> str:
    runs = repository.list_runs()
    status_counts = Counter(run.status.value for run in runs)
    total_artifacts = 0
    total_evaluations = 0
    evaluation_scores: list[float] = []
    node_counts: dict[tuple[str, str], int] = defaultdict(int)
    node_retries_total = 0
    error_events_total = 0

    for run in runs:
        total_artifacts += len(repository.list_artifacts(run.id))
        evaluations = repository.list_evaluations(run.id)
        total_evaluations += len(evaluations)
        evaluation_scores.extend(evaluation.score for evaluation in evaluations)
        error_events_total += sum(
            1 for event in repository.list_events(run.id) if event.event_type == "error"
        )
        for node in repository.list_graph_nodes(run.id):
            node_counts[(node.agent_type, node.status.value)] += 1
            node_retries_total += node.retry_count

    failed_runs_total = status_counts[RunStatus.FAILED.value]
    run_duration_seconds_sum = sum(
        max((run.updated_at - run.created_at).total_seconds(), 0.0) for run in runs
    )
    average_evaluation_score = (
        sum(evaluation_scores) / len(evaluation_scores) if evaluation_scores else 0.0
    )

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
            "# HELP aeai_evaluations_total Total evaluation records stored for runs.",
            "# TYPE aeai_evaluations_total gauge",
            f"aeai_evaluations_total {total_evaluations}",
            "# HELP aeai_evaluation_score_average Average score across stored evaluations.",
            "# TYPE aeai_evaluation_score_average gauge",
            f"aeai_evaluation_score_average {average_evaluation_score:.6f}",
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

    return "\n".join(lines) + "\n"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

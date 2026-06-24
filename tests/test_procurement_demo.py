from __future__ import annotations

import json

from aeai_os.schemas.enums import RunStatus
from scripts.run_procurement_demo import DEFAULT_DATASET_PATH, run_demo


def test_procurement_demo_produces_artifacts_and_trace_metadata(tmp_path):
    result = run_demo(
        dataset_path=DEFAULT_DATASET_PATH,
        artifact_root=tmp_path / "demo_artifacts",
    )

    artifact_types = {artifact["type"] for artifact in result.artifacts}
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    metrics = result.metrics_path.read_text(encoding="utf-8")

    assert result.status == RunStatus.COMPLETED
    assert result.trace_id
    assert {"dashboard", "report", "evaluation"}.issubset(artifact_types)
    assert result.evaluations[-1]["passed"] is True
    assert summary["run"]["trace_id"] == result.trace_id
    assert summary["run"]["status"] == "completed"
    assert summary["event_count"] == result.event_count
    assert "aeai_runs_total 1" in metrics
    assert "aeai_evaluations_total 1" in metrics

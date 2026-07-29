import json
from pathlib import Path

import yaml

from aeai_os.observability.metrics import render_prometheus_metrics
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import WorkflowJobStatus

ROOT = Path(__file__).resolve().parents[1]


def test_prometheus_scrape_config_targets_aeai_metrics_endpoint():
    config = yaml.safe_load((ROOT / "deploy/prometheus/prometheus.yml").read_text())
    scrape_jobs = {job["job_name"]: job for job in config["scrape_configs"]}

    api_job = scrape_jobs["aeai-api"]
    local_job = scrape_jobs["aeai-local-api"]
    assert api_job["metrics_path"] == "/metrics"
    assert api_job["static_configs"][0]["targets"] == ["api:8000"]
    assert api_job["static_configs"][0]["labels"]["component"] == "api"
    assert local_job["static_configs"][0]["targets"] == ["host.docker.internal:8000"]


def test_grafana_dashboard_import_json_references_expected_metrics():
    dashboard_path = (
        ROOT
        / "deploy/grafana/provisioning/dashboards/aeai-operational-dashboard.json"
    )
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    expressions = " ".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )
    assert dashboard["uid"] == "aeai-os-operations"
    assert "Run Latency" in panel_titles
    assert "Workflow Jobs" in panel_titles
    assert "Artifacts by Type" in panel_titles
    assert "aeai_runs_by_status" in expressions
    assert "aeai_workflow_jobs_total" in expressions
    assert "aeai_run_duration_seconds_bucket" in expressions
    assert "aeai_artifacts_by_type" in expressions


def test_slo_dashboard_references_production_objectives():
    dashboard_path = ROOT / "deploy/grafana/provisioning/dashboards/aeai-slo-dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    expressions = " ".join(
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    )

    assert dashboard["uid"] == "aeai-os-slos"
    assert "30-day API Availability" in panel_titles
    assert "Workflow p95 Latency" in panel_titles
    assert "Workflow Failure Ratio" in panel_titles
    assert "up" in expressions
    assert "aeai_run_duration_seconds_bucket" in expressions


def test_prometheus_metrics_include_workflow_and_histogram_series():
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement spend.")
    job = repository.enqueue_workflow_job(
        run_id=run.id,
        workflow_name="procurement",
        max_attempts=2,
    )
    claimed = repository.claim_workflow_job(job.id, worker_id="worker-one")
    assert claimed is not None
    repository.complete_workflow_job(claimed.id, worker_id="worker-one")

    metrics = render_prometheus_metrics(repository)

    assert 'aeai_workflow_jobs_total{workflow="procurement",status="completed"} 1' in metrics
    assert "aeai_workflow_job_attempts_total 1" in metrics
    assert "# TYPE aeai_run_duration_seconds histogram" in metrics
    assert "aeai_run_duration_seconds_bucket" in metrics
    assert "# TYPE aeai_workflow_job_duration_seconds histogram" in metrics
    assert "aeai_workflow_job_duration_seconds_bucket" in metrics
    assert (
        f'aeai_workflow_jobs_total{{workflow="procurement",'
        f'status="{WorkflowJobStatus.DEAD_LETTER.value}"}} 0'
    ) in metrics

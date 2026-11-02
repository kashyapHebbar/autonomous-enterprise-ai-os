from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.visualization.premium import render_premium_report_document


def _execute(tmp_path, filename, task):
    repository = InMemoryRunRepository()
    client = TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts"))
    run = client.post("/runs", json={"task": task, "dataset_uri": filename})
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]
    execution = client.post(f"/runs/{run_id}/execute")
    assert execution.status_code == 200, execution.text
    assert execution.json()["status"] == "completed", execution.text
    return client, repository, run_id, execution.json()


def test_procurement_executive_report_is_html_and_evaluation_still_checks_markdown(tmp_path):
    client, repository, run_id, output = _execute(
        tmp_path,
        "examples/procurement_demo.csv",
        "Analyze procurement spending and supplier risks with reports.",
    )
    reports = [a for a in output["artifacts"] if a["type"] == "report"]
    assert len(reports) == 2
    markdown = next(a for a in reports if a["metadata"]["format"] == "markdown")
    html = next(a for a in reports if a["metadata"]["format"] == "html")
    assert output["evaluations"][0]["passed"] is True
    assert output["evaluations"][0]["target_artifact_id"] == markdown["id"]
    response = client.get(f"/runs/{run_id}/artifacts/{html['id']}/content")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<h1>Procurement Analysis Report</h1>" in response.text
    assert "Spend &amp; concentration" in response.text
    assert "Supplier risk profiles" in response.text
    assert "<svg " in response.text
    assert "source-linked" in response.text.lower()
    assert markdown["id"] != html["id"]


def test_generic_workflow_creates_designed_report(tmp_path):
    client, repository, run_id, output = _execute(
        tmp_path,
        "examples/sales_demo.csv",
        "Analyze sales across regions, products and monthly revenue.",
    )
    reports = [a for a in output["artifacts"] if a["type"] == "report"]
    assert len(reports) == 2
    html = next(a for a in reports if a["metadata"]["format"] == "html")
    report_body = client.get(f"/runs/{run_id}/artifacts/{html['id']}/content").text
    assert "Exploratory Dataset Analysis Report" in report_body
    assert "Outliers &amp; quality" in report_body
    assert "Numeric measures" in report_body
    assert "169" not in report_body[:200]  # ensure no arbitrary test value used
    assert output["evaluations"][0]["passed"] is True


def test_untrusted_dataset_strings_are_html_escaped():
    analysis = {
        "analysis_type": "generic",
        "kpis": {
            "row_count": 2,
            "column_count": 1,
            "completeness": 1,
            "outlier_count": 0,
            "measure_count": 0,
            "dimension_count": 0,
            "duplicate_row_count": 0,
        },
        "analysis_plan": {
            "recipe": "generic",
            "measures": [],
            "dimensions": [],
            "time_columns": [],
            "identifiers": [],
        },
        "insights": ["<img src=x onerror=alert(1)>"],
        "recommendations": ["<script>alert(1)</script>"],
    }
    html = render_premium_report_document(analysis, ["source_artifact"])
    assert "<img src=x onerror=alert(1)>" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html

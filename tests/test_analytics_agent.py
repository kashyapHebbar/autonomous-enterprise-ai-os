from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from aeai_os.agents.analytics_code import AnalyticsCodeAgent
from aeai_os.agents.base import AgentInput
from aeai_os.analytics import CodeSafetyDecision, PythonCodeGuard, analyze_procurement_dataset
from aeai_os.analytics.reproducible import generate_reproducible_analysis_code
from aeai_os.data import CsvDatasetAdapter
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType


def write_analytics_fixture(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "supplier,category,invoice_date,spend_amount,department",
                "Acme,Software,2026-01-05,100,IT",
                "Acme,Software,2026-01-06,100,IT",
                "Zenith,Hardware,2026-02-01,200,Operations",
                "Acme,Cloud,2026-02-10,1000,IT",
                "Acme,,2026-02-11,,Finance",
                "Tiny,Office,2026-03-01,10,Finance",
            ]
        ),
        encoding="utf-8",
    )


def write_analytics_sqlite_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE procurement (
                supplier TEXT,
                category TEXT,
                invoice_date TEXT,
                spend_amount REAL,
                department TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO procurement VALUES (?, ?, ?, ?, ?)",
            [
                ("Acme", "Software", "2026-01-05", 100, "IT"),
                ("Acme", "Software", "2026-01-06", 100, "IT"),
                ("Zenith", "Hardware", "2026-02-01", 200, "Operations"),
                ("Acme", "Cloud", "2026-02-10", 1000, "IT"),
                ("Acme", "", "2026-02-11", None, "Finance"),
                ("Tiny", "Office", "2026-03-01", 10, "Finance"),
            ],
        )


def build_agent_fixture(tmp_path: Path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    csv_path = tmp_path / "procurement.csv"
    write_analytics_fixture(csv_path)
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=str(csv_path),
        metadata={"source": "test", "format": "csv"},
    )
    agent = AnalyticsCodeAgent(repository=repository, artifact_root=tmp_path / "artifacts")
    return repository, run, dataset, agent


def test_procurement_kpis_cover_spend_trends_outliers_savings_and_missing_risks(tmp_path):
    csv_path = tmp_path / "procurement.csv"
    write_analytics_fixture(csv_path)

    analysis = analyze_procurement_dataset(CsvDatasetAdapter.from_path(csv_path)).to_dict()

    assert analysis["kpis"] == {
        "total_spend": 1410.0,
        "supplier_count": 3,
        "category_count": 4,
        "average_transaction_value": 282.0,
        "outlier_count": 1,
        "estimated_savings": 86.2,
    }
    assert analysis["spend_by_supplier"][0] == {
        "supplier": "Acme",
        "spend": 1200.0,
        "share": 0.8511,
    }
    assert analysis["spend_trend"] == [
        {"month": "2026-01", "spend": 200.0},
        {"month": "2026-02", "spend": 1200.0},
        {"month": "2026-03", "spend": 10.0},
    ]
    assert analysis["outliers"][0]["amount"] == 1000.0
    assert {item["type"] for item in analysis["savings_opportunities"]} == {
        "supplier_concentration",
        "tail_supplier_consolidation",
        "outlier_review",
    }
    assert {item["field_role"] for item in analysis["missing_data_risks"]} == {
        "category",
        "amount",
    }


def test_procurement_kpis_support_common_public_spend_export_columns(tmp_path):
    csv_path = tmp_path / "public-spend.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Date,Expense Type,Supplier,Amount (GBP)",
                '30/03/2025,IT Software,Amazon Business,£699.25',
                '17/04/2025,Training,DATACAMP INC.,"£2,128.71"',
                "Jul-25,Cloud subscriptions,Example Cloud,£600",
            ]
        ),
        encoding="utf-8",
    )

    analysis = analyze_procurement_dataset(CsvDatasetAdapter.from_path(csv_path)).to_dict()

    assert analysis["kpis"]["total_spend"] == 3427.96
    assert analysis["dataset"]["currency"] == "GBP"
    assert analysis["dataset"]["currency_symbol"] == "£"
    assert analysis["insights"][0] == "Total analyzed procurement spend is £3,427.96."
    assert analysis["dataset"]["resolved_columns"] == {
        "supplier": "Supplier",
        "category": "Expense Type",
        "amount": "Amount (GBP)",
        "date": "Date",
    }
    assert analysis["spend_trend"] == [
        {"month": "2025-03", "spend": 699.25},
        {"month": "2025-04", "spend": 2128.71},
        {"month": "2025-07", "spend": 600.0},
    ]


def test_analytics_agent_registers_kpi_and_reproducible_code_artifacts(tmp_path):
    repository, run, dataset, agent = build_agent_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id},
        )
    )

    kpi_artifact = repository.get_artifact(run.id, output.artifacts[0])
    code_artifact = repository.get_artifact(run.id, output.artifacts[1])
    analysis = json.loads(Path(kpi_artifact.uri).read_text(encoding="utf-8"))
    source_code = Path(code_artifact.uri).read_text(encoding="utf-8")

    assert output.status == "succeeded"
    assert kpi_artifact.type == ArtifactType.KPI_TABLE
    assert code_artifact.type == ArtifactType.CODE
    assert kpi_artifact.source_artifact_ids == [dataset.id]
    assert analysis["kpis"]["total_spend"] == 1410.0
    assert analysis["insights"]
    assert PythonCodeGuard().evaluate(source_code).decision == CodeSafetyDecision.SAFE
    compile(source_code, code_artifact.uri, "exec")
    assert code_artifact.metadata["execution_mode"] == "validated_artifact_only"


def test_analytics_agent_analyzes_sqlite_warehouse_reference(tmp_path):
    repository = InMemoryRunRepository()
    run = repository.create_run("Analyze procurement data.")
    db_path = tmp_path / "warehouse.db"
    write_analytics_sqlite_fixture(db_path)
    dataset = repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.DATASET,
        uri=f"sqlite://{db_path}#procurement",
        metadata={"source": "warehouse", "format": "sqlite"},
    )
    agent = AnalyticsCodeAgent(repository=repository, artifact_root=tmp_path / "artifacts")

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id},
        )
    )

    kpi_artifact = repository.get_artifact(run.id, output.artifacts[0])
    analysis = json.loads(Path(kpi_artifact.uri).read_text(encoding="utf-8"))

    assert output.status == "succeeded"
    assert output.metrics["adapter"] == "SqliteWarehouseConnector"
    assert analysis["kpis"]["total_spend"] == 1410.0
    assert analysis["dataset"]["row_count"] == 6


def test_code_guard_blocks_network_and_process_access():
    guard = PythonCodeGuard()

    network_report = guard.evaluate("import requests\nrequests.get('https://example.com')")
    process_report = guard.evaluate("import subprocess\nsubprocess.run(['echo', 'unsafe'])")

    assert network_report.decision == CodeSafetyDecision.BLOCKED
    assert process_report.decision == CodeSafetyDecision.BLOCKED
    assert network_report.violations[0].rule == "blocked_import"


def test_analytics_agent_blocks_prohibited_generated_code(tmp_path):
    repository, run, dataset, agent = build_agent_fixture(tmp_path)

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={
                "dataset_artifact_id": dataset.id,
                "analysis_code": "import requests\nrequests.get('https://example.com')",
            },
        )
    )

    assert output.status == "failed"
    assert "not allowed" in output.errors[0]
    assert len(repository.list_artifacts(run.id)) == 1


def test_analytics_agent_pauses_when_generated_code_requires_approval(tmp_path):
    repository, run, dataset, agent = build_agent_fixture(tmp_path)
    write_code = "with open('result.txt', 'w') as handle:\n    handle.write('result')"

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id, "analysis_code": write_code},
        )
    )

    assert output.status == "waiting_for_approval"
    assert output.metrics["safety_report"]["decision"] == "approval_required"
    assert len(repository.list_artifacts(run.id)) == 1


def test_analytics_agent_accepts_approval_required_code_after_explicit_approval(tmp_path):
    repository, run, dataset, agent = build_agent_fixture(tmp_path)
    write_code = "with open('result.txt', 'w') as handle:\n    handle.write('result')"

    output = agent.execute(
        AgentInput(
            run_id=run.id,
            node_id="analytics",
            task="Compute procurement KPIs.",
            context={"dataset_artifact_id": dataset.id, "analysis_code": write_code},
            approvals=["approved"],
        )
    )

    code_artifact = repository.get_artifact(run.id, output.artifacts[1])
    assert output.status == "succeeded"
    assert code_artifact.metadata["safety_decision"] == "approval_required"
    assert code_artifact.metadata["execution_mode"] == "validated_artifact_only"


def test_reproducible_analysis_template_is_safe():
    source = generate_reproducible_analysis_code()

    assert PythonCodeGuard().evaluate(source).decision == CodeSafetyDecision.SAFE
    compile(source, "procurement_analysis.py", "exec")

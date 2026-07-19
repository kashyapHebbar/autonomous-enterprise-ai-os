from __future__ import annotations

import json

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.schemas.enums import ArtifactType

TOKEN_PROFILES = (
    "acme-token=acme-operator|Acme Operator|operator|acme|finance;"
    "globex-token=globex-operator|Globex Operator|operator|globex|finance"
)
ACME = {"Authorization": "Bearer acme-token"}
GLOBEX = {"Authorization": "Bearer globex-token"}


def _client_with_case(tmp_path, monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", TOKEN_PROFILES)
    repository = InMemoryRunRepository()
    run = repository.create_run(
        "Investigate procurement anomalies.",
        metadata={"organization_id": "acme", "workspace_id": "finance"},
    )
    payload_path = tmp_path / "analysis.json"
    payload_path.write_text(
        json.dumps(
            {
                "dataset": {"currency": "GBP"},
                "anomalies": [
                    {
                        "id": "anomaly-row-7",
                        "row_number": 7,
                        "supplier": "Acme",
                        "category": "Software",
                        "amount": 9500,
                        "risk_score": 82,
                        "severity": "critical",
                        "confidence": 0.91,
                        "reason": "Duplicate invoice; Supplier amount spike",
                        "signals": [
                            {
                                "code": "duplicate_invoice",
                                "weight": 60,
                                "evidence": "Invoice INV-7 appears twice.",
                            }
                        ],
                        "recommended_action": "Hold for immediate investigation.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repository.add_artifact(
        run_id=run.id,
        artifact_type=ArtifactType.KPI_TABLE,
        uri=str(payload_path),
    )
    return TestClient(create_app(repository=repository, artifact_root=tmp_path / "artifacts")), run


def test_investigation_queue_is_tenant_scoped(tmp_path, monkeypatch):
    client, run = _client_with_case(tmp_path, monkeypatch)

    own = client.get("/investigations", headers=ACME)
    other = client.get("/investigations", headers=GLOBEX)
    summary = client.get("/investigations/summary", headers=ACME)

    assert own.status_code == 200
    assert own.json()[0]["run_id"] == run.id
    assert own.json()[0]["status"] == "new"
    assert own.json()[0]["currency"] == "GBP"
    assert other.json() == []
    assert summary.json()["critical"] == 1
    assert summary.json()["risk_exposure"] == 9500
    assert summary.json()["risk_exposure_by_currency"] == {"GBP": 9500}


def test_investigation_updates_are_durable_audited_feedback(tmp_path, monkeypatch):
    client, run = _client_with_case(tmp_path, monkeypatch)

    update = client.patch(
        f"/investigations/{run.id}/anomaly-row-7",
        headers=ACME,
        json={
            "status": "confirmed",
            "assignee": "fraud-review@example.com",
            "comment": "Invoice duplicated after an ERP retry.",
            "disposition_reason": "Confirmed duplicate payment risk.",
        },
    )
    refreshed = client.get(f"/investigations/{run.id}/anomaly-row-7", headers=ACME)

    assert update.status_code == 200
    assert refreshed.json()["status"] == "confirmed"
    assert refreshed.json()["assignee"] == "fraud-review@example.com"
    assert refreshed.json()["history"][0]["actor"]["organization_id"] == "acme"
    assert refreshed.json()["history"][0]["comment"] == "Invoice duplicated after an ERP retry."


def test_confirmed_or_dismissed_case_requires_rationale(tmp_path, monkeypatch):
    client, run = _client_with_case(tmp_path, monkeypatch)

    response = client.patch(
        f"/investigations/{run.id}/anomaly-row-7",
        headers=ACME,
        json={"status": "dismissed"},
    )

    assert response.status_code == 422

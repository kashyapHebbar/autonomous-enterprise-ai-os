from __future__ import annotations

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app
from aeai_os.security.oidc import authenticated_user_from_oidc_token

TOKEN_PROFILES = (
    "acme-token=acme-admin|Acme Admin|admin|acme|finance,operations;"
    "globex-token=globex-admin|Globex Admin|admin|globex|finance"
)
ACME_HEADERS = {"Authorization": "Bearer acme-token"}
GLOBEX_HEADERS = {"Authorization": "Bearer globex-token"}


def _authenticated_client(monkeypatch):
    monkeypatch.setenv("AEAI_AUTH_ENABLED", "true")
    monkeypatch.setenv("AEAI_AUTH_TOKEN_PROFILES", TOKEN_PROFILES)
    return TestClient(create_app())


def test_session_exposes_server_derived_tenant_and_workspace(monkeypatch):
    client = _authenticated_client(monkeypatch)

    response = client.get(
        "/auth/me",
        headers={**ACME_HEADERS, "X-AEAI-Workspace-ID": "operations"},
    )

    assert response.status_code == 200
    assert response.json()["organization_id"] == "acme"
    assert response.json()["active_workspace_id"] == "operations"
    assert response.json()["workspace_ids"] == ["finance", "operations"]


def test_unauthorized_workspace_header_is_rejected(monkeypatch):
    client = _authenticated_client(monkeypatch)

    response = client.get(
        "/runs",
        headers={**ACME_HEADERS, "X-AEAI-Workspace-ID": "executive"},
    )

    assert response.status_code == 403


def test_runs_and_nested_artifacts_are_hidden_across_organizations(monkeypatch):
    client = _authenticated_client(monkeypatch)
    created = client.post(
        "/runs",
        headers=ACME_HEADERS,
        json={
            "task": "Analyze finance spend.",
            "metadata": {"organization_id": "globex", "workspace_id": "stolen"},
        },
    )

    run = created.json()
    artifact = client.post(
        f"/runs/{run['id']}/datasets/reference",
        headers=ACME_HEADERS,
        json={"uri": "s3://acme/procurement.csv", "format": "csv"},
    ).json()

    assert created.status_code == 201
    assert run["metadata"]["organization_id"] == "acme"
    assert run["metadata"]["workspace_id"] == "finance"
    assert client.get("/runs", headers=GLOBEX_HEADERS).json() == []
    assert client.get(f"/runs/{run['id']}", headers=GLOBEX_HEADERS).status_code == 404
    assert (
        client.get(
            f"/runs/{run['id']}/artifacts/{artifact['id']}", headers=GLOBEX_HEADERS
        ).status_code
        == 404
    )
    archive = client.get(f"/runs/{run['id']}/export", headers=ACME_HEADERS).json()
    overwrite = client.post(
        "/runs/import",
        headers=GLOBEX_HEADERS,
        json={"archive": archive, "overwrite": True},
    )
    assert overwrite.status_code == 404


def test_connectors_ignore_caller_supplied_organization(monkeypatch):
    client = _authenticated_client(monkeypatch)
    created = client.post(
        "/connectors/installations",
        headers=ACME_HEADERS,
        json={
            "connector_id": "local-file",
            "name": "Acme files",
            "organization_id": "globex",
            "workspace_id": "executive",
        },
    )

    assert created.status_code == 201
    assert created.json()["organization_id"] == "acme"
    assert created.json()["workspace_id"] == "finance"
    assert client.get("/connectors/installations", headers=GLOBEX_HEADERS).json() == []
    assert (
        client.post(
            f"/connectors/installations/{created.json()['id']}/test",
            headers=GLOBEX_HEADERS,
        ).status_code
        == 404
    )


def test_data_sources_are_workspace_scoped(monkeypatch, tmp_path):
    client = _authenticated_client(monkeypatch)
    dataset = tmp_path / "procurement.csv"
    dataset.write_text("supplier,spend_amount\nAcme,100\n", encoding="utf-8")
    created = client.post(
        "/data-sources",
        headers=ACME_HEADERS,
        json={
            "id": "procurement",
            "name": "Procurement spend",
            "source_type": "local_file",
            "dataset_uri": str(dataset),
            "owner": "finance-platform",
        },
    )

    assert created.status_code == 201
    assert created.json()["organization_id"] == "acme"
    assert created.json()["workspace_id"] == "finance"
    assert client.get("/data-sources", headers=GLOBEX_HEADERS).json() == []
    assert client.get("/data-sources/procurement", headers=GLOBEX_HEADERS).status_code == 404


def test_oidc_claims_map_to_enterprise_identity():
    user = authenticated_user_from_oidc_token(
        "verified-by-test-double",
        issuer="https://identity.example.com",
        audience="aeai-os",
        jwks_url="https://identity.example.com/.well-known/jwks.json",
        claims={
            "sub": "user-42",
            "name": "Enterprise User",
            "roles": ["operator", "reviewer"],
            "organization_id": "acme",
            "workspace_ids": ["finance", "operations"],
        },
    )

    assert user.id == "user-42"
    assert user.organization_id == "acme"
    assert user.workspace_ids == ("finance", "operations")

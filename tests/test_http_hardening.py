from __future__ import annotations

from fastapi.testclient import TestClient

from aeai_os.api.app import create_app


def test_api_responses_include_security_headers():
    response = TestClient(create_app()).get("/health", headers={"x-forwarded-proto": "https"})

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["strict-transport-security"].startswith("max-age=31536000")


def test_api_rejects_oversized_request_before_reading_body(monkeypatch):
    monkeypatch.setenv("AEAI_MAX_REQUEST_BODY_BYTES", "16")
    response = TestClient(create_app()).post(
        "/runs",
        content=b"x" * 17,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the configured limit."}

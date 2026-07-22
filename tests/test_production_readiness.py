from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import manage_recovery, production_readiness
from scripts.release_operations import render_production_manifest
from scripts.validate_production_readiness import validate_production_readiness


def test_load_gate_calculates_thresholds(monkeypatch):
    observations = iter(
        [
            production_readiness.RequestObservation(200, 25),
            production_readiness.RequestObservation(200, 40),
            production_readiness.RequestObservation(200, 55),
            production_readiness.RequestObservation(503, 70, "unavailable"),
        ]
    )
    monkeypatch.setattr(production_readiness, "_observe_request", lambda *args: next(observations))

    result = production_readiness.run_load_test(
        "https://api.example.com/health",
        request_count=4,
        concurrency=1,
        timeout_seconds=1,
        max_error_rate=0.25,
        max_p95_ms=75,
    )

    assert result.successful == 3
    assert result.error_rate == 0.25
    assert result.p95_ms == 70
    assert result.passed is True


def test_security_gate_requires_expected_headers(monkeypatch):
    class Response:
        status = 200
        headers = {
            "Content-Security-Policy": "default-src 'self'",
            "Permissions-Policy": "camera=()",
            "Referrer-Policy": "no-referrer",
            "Strict-Transport-Security": "max-age=31536000",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(production_readiness, "urlopen", lambda *args, **kwargs: Response())

    assert production_readiness.check_security_headers("https://api.example.com/health") == []


def test_release_manifest_rendering_replaces_public_values():
    template = (
        "host: REPLACE_WITH_PUBLIC_HOSTNAME\n"
        "certificate: REPLACE_WITH_ACM_CERTIFICATE_ARN\n"
        "waf: REPLACE_WITH_WAF_ACL_ARN\n"
    )
    rendered = render_production_manifest(
        template,
        {
            "AEAI_PUBLIC_HOSTNAME": "production-host",
            "AEAI_ACM_CERTIFICATE_ARN": "arn:aws:acm:certificate/test",
            "AEAI_WAF_ACL_ARN": "arn:aws:wafv2:webacl/test",
        },
    )

    assert "production-host" in rendered
    assert "REPLACE_WITH" not in rendered


def test_release_manifest_rendering_rejects_missing_values():
    with pytest.raises(ValueError, match="AEAI_WAF_ACL_ARN"):
        render_production_manifest(
            "REPLACE_WITH_PUBLIC_HOSTNAME REPLACE_WITH_ACM_CERTIFICATE_ARN "
            "REPLACE_WITH_WAF_ACL_ARN",
            {
                "AEAI_PUBLIC_HOSTNAME": "production-host",
                "AEAI_ACM_CERTIFICATE_ARN": "arn:aws:acm:certificate/test",
            },
        )


def test_release_manifest_rendering_rejects_mutable_image():
    with pytest.raises(ValueError, match="immutable sha256"):
        render_production_manifest(
            "image: ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:production",
            {"AEAI_IMAGE_REFERENCE": "ghcr.io/example/aeai-os:latest"},
        )


def test_recovery_url_is_converted_to_pg_environment():
    env, database = manage_recovery.postgres_environment(
        "postgresql+psycopg://aeai:secret@db.example.com:5433/aeai_restore_drill"
    )

    assert database == "aeai_restore_drill"
    assert env["PGHOST"] == "db.example.com"
    assert env["PGPORT"] == "5433"
    assert env["PGUSER"] == "aeai"
    assert env["PGPASSWORD"] == "secret"


def test_restore_drill_requires_safety_marker(tmp_path):
    backup = tmp_path / "database.dump"
    backup.write_bytes(b"backup")

    with pytest.raises(ValueError, match="safety marker"):
        manage_recovery.restore_backup(
            "postgresql://aeai:secret@localhost/aeai_production",
            backup,
            allow_target="restore_drill",
        )


def test_backup_writes_checksum_manifest(monkeypatch, tmp_path):
    output = tmp_path / "database.dump"

    def fake_run(command, **kwargs):
        output.write_bytes(b"portable backup")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(manage_recovery.subprocess, "run", fake_run)
    manifest = manage_recovery.create_backup(
        "postgresql://aeai:secret@localhost/aeai_os",
        output,
    )

    written = json.loads(output.with_suffix(".dump.json").read_text(encoding="utf-8"))
    assert manifest["sha256"] == written["sha256"]
    assert written["size_bytes"] == len(b"portable backup")


def test_restore_rejects_tampered_backup(monkeypatch, tmp_path):
    output = tmp_path / "database.dump"

    def fake_dump(command, **kwargs):
        output.write_bytes(b"original backup")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(manage_recovery.subprocess, "run", fake_dump)
    manage_recovery.create_backup(
        "postgresql://aeai:secret@localhost/aeai_os",
        output,
    )
    output.write_bytes(b"tampered backup")

    with pytest.raises(ValueError, match="checksum"):
        manage_recovery.restore_backup(
            "postgresql://aeai:secret@localhost/aeai_restore_drill",
            output,
            allow_target="restore_drill",
        )


def test_production_readiness_package_passes_static_validation():
    assert validate_production_readiness() == []


def test_operations_docs_are_present():
    root = Path("docs/operations")
    assert {path.name for path in root.glob("*.md")} >= {
        "backup-and-recovery.md",
        "incident-runbooks.md",
        "production-readiness.md",
        "security-validation.md",
    }

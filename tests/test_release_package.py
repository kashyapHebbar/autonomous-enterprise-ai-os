from __future__ import annotations

import json
from pathlib import Path

from scripts.build_release_package import build_release_package

RELEASE_DOCS = Path("docs/release")


def test_v1_release_checklist_covers_launch_readiness_areas():
    text = (RELEASE_DOCS / "v1.0-checklist.md").read_text(encoding="utf-8")

    for token in [
        "## Release Candidate",
        "## Validation",
        "## Documentation",
        "## Product Surfaces",
        "## Demo Flow",
        "## Security And Governance",
        "## Observability",
        "## Deployment",
        "## Final v1.0 Acceptance Criteria",
        "make release-package",
    ]:
        assert token in text


def test_v1_release_notes_explain_platform_value_and_scope():
    text = (RELEASE_DOCS / "v1.0-release-notes.md").read_text(encoding="utf-8")

    for token in [
        "planner-generated execution graphs",
        "durable orchestration",
        "Browser control plane",
        "Security governance",
        "Kubernetes overlays",
        "AWS deployment path",
        "Out Of Scope",
    ]:
        assert token in text


def test_v1_demo_walkthrough_and_assets_cover_ui_review_flow():
    walkthrough = (RELEASE_DOCS / "v1.0-demo-walkthrough.md").read_text(encoding="utf-8")
    assets = (RELEASE_DOCS / "v1.0-demo-assets.md").read_text(encoding="utf-8")

    for token in [
        "make demo",
        "examples/procurement_demo.csv",
        "/app",
        "/app/artifacts",
        "/app/admin",
        "/run-inspector/runs/{run_id}",
        "/metrics",
    ]:
        assert token in walkthrough

    for asset in [
        "01-control-plane.png",
        "02-admin-ui.png",
        "03-artifact-browser.png",
        "04-run-inspector.png",
        "Short Demo Clip Outline",
    ]:
        assert asset in assets


def test_release_package_builder_creates_portable_manifest(tmp_path):
    manifest_path = build_release_package(tmp_path / "package")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    expected_files = {
        "README.md",
        "DEMO_PACKAGE.md",
        "docs/portfolio-architecture.md",
        "docs/release/v1.0-checklist.md",
        "docs/release/v1.0-release-notes.md",
        "docs/release/v1.0-demo-walkthrough.md",
        "docs/release/v1.0-demo-assets.md",
        "examples/procurement_demo.csv",
    }
    assert expected_files.issubset(set(manifest["files"]))
    assert "make release-package" in manifest["validation_commands"]
    assert "http://127.0.0.1:8000/app/admin" in manifest["ui_links"]

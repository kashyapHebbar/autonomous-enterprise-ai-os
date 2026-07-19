from __future__ import annotations

from pathlib import Path

PORTFOLIO_DOC = Path("docs/portfolio-architecture.md")
README = Path("README.md")


def test_portfolio_architecture_doc_has_required_reviewer_sections():
    text = PORTFOLIO_DOC.read_text(encoding="utf-8")

    for heading in [
        "## Executive Summary",
        "## System Context",
        "## Component Responsibilities",
        "## Procurement Workflow Graph",
        "## API, Worker, And State Flow",
        "## Storage, Connectors, And Lineage",
        "## Observability And Operations",
        "## UI Map",
        "## Setup Paths",
        "## Demo Flow For Reviewers",
    ]:
        assert heading in text

    assert text.count("```mermaid") >= 5


def test_portfolio_architecture_doc_links_ui_and_setup_paths():
    text = PORTFOLIO_DOC.read_text(encoding="utf-8")

    for token in [
        "/app",
        "/app/artifacts",
        "/app/admin",
        "/run-inspector/runs/{run_id}",
        "/docs",
        "make demo",
        "make k8s-validate",
        "make cloud-validate",
        "deploy/kubernetes/overlays/production",
        "deploy/cloud/aws/terraform",
    ]:
        assert token in text


def test_portfolio_architecture_doc_explains_platform_components():
    text = PORTFOLIO_DOC.read_text(encoding="utf-8")

    for token in [
        "FastAPI API",
        "Workflow worker",
        "Run repository",
        "Artifact storage",
        "Connector registry",
        "Security policy",
        "OpenTelemetry",
        "Prometheus",
        "Grafana",
        "AWS cloud",
    ]:
        assert token in text


def test_readme_points_to_portfolio_architecture_doc():
    text = README.read_text(encoding="utf-8")

    assert "docs/portfolio-architecture.md" in text
    assert "Portfolio architecture" in text

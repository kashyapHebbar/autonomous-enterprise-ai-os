"""Offline source and integration contracts for the Operations Center UI refresh."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend/src/pages/Operations.tsx"
STYLE = ROOT / "frontend/src/operations.css"


def test_operations_status_remains_connected_to_live_apis():
    text = PAGE.read_text()
    for feature in (
        "api.operations",
        "api.monitoringSummary",
        "refetchInterval",
        "retryDeadLetter",
    ):
        assert feature in text
    assert "operations/status" not in text  # the shared API client owns routes
    assert "window.prompt" in text  # an explicit reason remains required before retry


def test_queue_controls_are_real_not_decorative():
    text = PAGE.read_text()
    for feature in (
        "setFilter(f.key)",
        "setSearch(e.target.value)",
        "filter === 'all'",
        "search.trim().toLowerCase()",
        "jobs.map(job",
        "job.run_id",
    ):
        assert feature in text


def test_existing_links_and_safe_controls_preserved():
    text = PAGE.read_text()
    for route in ("/workflows", "/monitoring", "/data", "/usage"):
        assert route in text
    assert "api.retryDeadLetter" in text
    assert "fetch('/" not in text
    assert "exec(" not in text
    assert "localStorage" not in text


def test_new_layout_is_responsive_and_reduced_motion_aware():
    css = STYLE.read_text()
    for name in (
        ".ops-v2-hero",
        ".ops-v2-metrics",
        ".ops-v2-service",
        ".ops-v2-job",
        ".ops-v2-tabs",
        ".ops-v2-diagnostics",
        ".ops-home-status",
    ):
        assert name in css
    assert "@media(max-width:620px)" in css
    assert "prefers-reduced-motion:reduce" in css

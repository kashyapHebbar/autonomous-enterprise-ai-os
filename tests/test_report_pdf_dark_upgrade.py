"""Dark-mode documents and browser-native PDF-print support.

The UI calls iframe.contentWindow.print() from a user action. The browser's
native Print / Save as PDF dialog performs the conversion, not a server plugin.
"""

from aeai_os.visualization.premium import (
    DARK_CSS,
    render_premium_report_document,
)


def test_generated_reports_default_to_dark_and_still_have_light_theme():
    report = render_premium_report_document(
        {
            "analysis_type": "generic",
            "kpis": {"row_count": 1, "column_count": 1, "completeness": 1.0},
            "analysis_plan": {
                "recipe": "generic",
                "measures": [],
                "dimensions": [],
                "time_columns": [],
                "identifiers": [],
            },
        },
        ["source-id"],
    )
    assert '<html lang="en" data-theme="dark">' in report
    assert ':root[data-theme="dark"]' in report
    assert "color-scheme: dark;" in report
    assert "color-scheme:light" in report
    assert "@media print" in DARK_CSS
    assert "Save as PDF:" in report
    # The report does not require an unsafe inline script to invoke printing.
    assert "window.print()" not in report


def test_print_style_avoids_dark_ink_on_dark_paper():
    assert (
        '[data-theme="dark"] body {background:#fff!important;color:#182138!important}' in DARK_CSS
    )
    assert (
        '[data-theme="dark"] .stat, [data-theme="dark"] .card {background:#fff!important;'
        in DARK_CSS
    )


def test_preview_uses_script_free_sandbox_and_browser_native_print():
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[1] / "frontend/src/components"
    preview = (frontend / "ArtifactPreview.tsx").read_text()
    explorer = (frontend / "ArtifactExplorer.tsx").read_text()
    assert "reportWindow.print()" in preview
    assert 'sandbox="allow-same-origin allow-modals"' in preview
    assert "allow-scripts" not in preview
    assert "MutationObserver(sync)" in preview
    assert "Save as PDF" in preview
    assert "ae-pdf-list-button" in explorer

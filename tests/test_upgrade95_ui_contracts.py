"""Upgrade 9.5 safe UI integration checks; no network and no Hugging Face calls."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"


def read(path: str) -> str:
    return (SRC / path).read_text(encoding="utf-8")


def test_existing_workflow_apis_remain_connected():
    api = read("api.ts")
    assert "runQuestions:" in api and "askRun:" in api
    assert "executeRun:" in api and "enqueueRun:" in api
    assert "artifactContent:" in api and "artifactUrl:" in api


def test_navigation_keeps_legacy_governance_access_and_new_pages():
    layout = read("components/Layout.tsx")
    app = read("App.tsx")
    for route in ("/workflows", "/artifacts", "/analyst", "/compare", "/settings", "/usage"):
        assert route in layout
    for path in (
        'path="workflows/:runId"',
        'path="analyst"',
        'path="compare"',
        'path="data/explore"',
    ):
        assert path in app
    assert "/governance" in layout and "/observability" in layout


def test_ui_only_and_budget_neutral():
    for path in (
        "pages/Home.tsx",
        "pages/CompareRuns.tsx",
        "pages/UsageCenter.tsx",
        "pages/Settings.tsx",
    ):
        src = read(path)
        assert "OPENAI_API_KEY" not in src
        assert "HF_TOKEN" not in src
        assert "router.huggingface.co" not in src
    assert "onClick={()=>window.dispatchEvent(new Event('aeai:new-workflow'))}" in read(
        "pages/Home.tsx"
    )


def test_exports_exclude_source_and_arbitrary_code():
    src = read("lib/investigationExport.ts")
    assert "a.type!=='dataset'" in src
    assert "a.type!=='code'" in src
    assert "README-MANIFEST.json" in src
    assert "60 MB package limit" in src


def test_saved_results_and_ai_questions_are_preserved():
    detail = read("pages/WorkflowDetail.tsx")
    assert "ResultsSummary" in detail and "ArtifactExplorer" in detail
    assert "AskRunPanel" in detail and "AiUsagePanel" in detail
    assert "ExecutionTimeline" in detail
    assert "downloadInvestigationPackage" in detail


def test_preferences_are_client_only_and_use_existing_browser_storage():
    pref = read("lib/uiPreferences.ts")
    assert "localStorage" in pref
    assert "getUiPrefs" in pref and "updateUiPrefs" in pref
    assert "setUiPrefs" not in pref


def test_preserve_user_fastapi_subpath_and_original_ui_link():
    assert '<BrowserRouter basename="/app">' in read("main.tsx")
    assert 'href="/legacy-app"' in read("components/Layout.tsx")

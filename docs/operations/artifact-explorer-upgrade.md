# Upgrade 3 — Grouped Artifacts & Execution Explorer

This frontend-only upgrade keeps the established FastAPI APIs, premium report generator,
async queue, tests, and `/app` integration intact.

## Features

- Workflow Details: **Outputs**, **Execution**, and **Logs** tabs.
- Outputs grouped automatically into Executive reports, Visual dashboards,
  Charts & visuals, Data & evidence, and Source & technical.
- Shared group explorer in Workflow Details and Reports & Artifacts; search,
  category and producing-agent filters. Counts come from API artifact records.
- Actual **Preview**, **Download**, and **Details / Lineage** actions.
- HTML documents are fetched over the authorized API and rendered with
  `iframe srcDoc` in a restrictive sandbox. No script, form, same-origin, or
  top-level navigation permissions are granted. This is deliberately used instead
  of direct iframe URLs because the backend enforces `X-Frame-Options: DENY`.
- JSON and text previews are fetched and rendered as escaped React text. Markdown
  gets a safe lightweight heading/list view without executing HTML.
- Dataset references only display details: the backend prohibits downloading
  dataset artifacts through the content endpoint.
- Execution Logs: full event history, search, type and agent filters,
  local timestamps, expanded event payloads, and links from agent events and graph
  nodes to the output group filtered to the corresponding producer.
- No fabricated timeline messages or fake agent completion percentages.

## Installation in existing VS Code folder

1. Stop `make dev` with Ctrl+C.
2. From the project root, run `python3 ~/Downloads/AEAI-Upgrade3-Apply.py`.
   The installer checks expected Upgrade 1 + Report Design V2 files and makes
   a timestamped backup before applying the patch. It does not change app.py.
3. `source .venv/bin/activate && python -m pytest -q tests/test_artifact_explorer_upgrade.py`
4. `python -m pytest -q`
5. `eval "$(/opt/homebrew/bin/brew shellenv)"` on Apple Silicon if an old Intel
   `node` shadows your native installation.
6. `cd frontend && npm run build && cd .. && make dev`.
7. Open `http://127.0.0.1:8000/app`. Use an existing completed run or create
   a new one. Open the run → Outputs / Execution / Logs, then the Reports &
   Artifacts library. Old artifacts also display in groups.

## Notes

- The UI is static TypeScript/React; grouping doesn't require a new database table.
- Existing run records are still in-memory under your local dev defaults and
  disappear after a backend restart. Artifact files may remain on disk.
- The premium HTML report may contain external fonts or other static assets;
  the embedded preview disallows script execution and site navigation. Use the
  provided Open action to view the original document if a sandbox feature is
  necessary, and Download to save the original bytes.
- This upgrade does not add new event sources or alter log retention. It changes
  how existing run-scoped event records are searched and displayed.
- On failed or unbuilt React bundles, the existing Python backend remains unchanged.

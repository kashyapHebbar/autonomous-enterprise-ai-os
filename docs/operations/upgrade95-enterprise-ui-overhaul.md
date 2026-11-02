# AEAI OS Upgrade 9.5 — Enterprise UI Overhaul

This upgrade builds upon Upgrade 9 and **changes only the React UI and its frontend-only utilities**. No backend routes, authorization controls, prompts, model weights, analysis calculations, report HTML contents, evaluation logic, or Hugging Face integration are changed.

## Installation

From the existing AI OS repository on macOS:

```bash
cd ~/projects/autonomous-enterprise-ai-os
source .venv/bin/activate
python3 ~/Downloads/AEAI-Upgrade95-Apply.py
python -m pytest -q tests/test_upgrade95_ui_contracts.py
npm --prefix frontend run build
make dev
```

If native `node` is missing on an Apple Silicon Mac, run:

```zsh
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
node -p 'process.arch' # should print arm64
npm --prefix frontend run build
```

The installer accepts only known, unmodified Upgrade 9 UI files and files it already installed. It creates a timestamped backup before overwriting files and aborts without changes if a local edit would be lost. Use `--check` to run preflight checks without changing files. The original `planner.py` repair is not touched.

## What changed

- New dark/light visual system, refined typographic hierarchy, premium Command Center, responsive cards, genuine six-month workflow activity chart, live attention list.
- Unified navigation: Home, Investigations, Data Sources, Results Library, AI Insights, AI Analyst, Compare Analyses, AI Usage and Settings; technical Governance and System Monitoring remain accessible and can be revealed in the sidebar from Settings.
- Keyboard search (Cmd/Ctrl+K) across pages and saved workflow titles; local notifications based on actual run statuses.
- Guided three-step workflow creation with demo, registered data source, or backend-accessible CSV path.
- Dedicated AI Analyst page reusing the existing evidence-backed Q&A; no HF calls until user explicitly asks.
- Dataset overview reads **saved schema profile artifacts**, not raw source CSV data. It deliberately does not expose unredacted row-level previews.
- Side-by-side comparison of persisted numerical KPI fields in two completed runs. It warns when analysis types differ; it does not pretend that percentages are causal effects.
- AI Usage Center aggregates **available saved run events**, not your account's HF bill or exact current credit balance.
- Results page shows verified KPIs, saved findings and a read-only ZIP export containing generated output files plus their provenance manifest. The exporter omits the original dataset and code, and enforces per-file and total size limits.
- Browser-local visual preferences for theme, density, motion and advanced navigation.

## Limitations (deliberately not misrepresented as implemented)

- No general row-level CSV preview, because that requires a new permission-checked and redacted backend endpoint.
- No arbitrary LLM-generated charts or new analytics calculations: those belong to planned Upgrade 10.
- This is not full project-wide search over raw report bodies; Cmd/Ctrl+K searches navigation and workflow titles.
- Browser-local preferences are not synced between devices; the product's existing authentication and RBAC remain authoritative.
- The ZIP result bundle includes generated output files with a manifest, but HTML outputs may depend on external assets not embedded in the archive.
- The usage total considers up to 30 recent workflow event logs and can span months; HF billing is authoritative.

## Safety and rollback

The installer stores original files in `.upgrade95-ui-backup-<timestamp>/`. To roll back, stop FastAPI, then restore backed-up files and remove files noted as newly created in `upgrade95-manifest.json`. Do not delete unrelated files. Backup and conflict detection require no inference requests. Tests are deterministic.


### Compatibility with the existing local FastAPI integration

This compatible build preserves the user-provided `BrowserRouter basename="/app"` so
client-side routes continue working when the built frontend is served by FastAPI
at `/app`. It also keeps the `/legacy-app` link to the previous interface.
The preflight is bound to the uploaded Layout.tsx and main.tsx SHA-256
checksums; it does not broadly override conflict protection.

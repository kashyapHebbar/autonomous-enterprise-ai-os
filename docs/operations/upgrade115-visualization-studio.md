# Upgrade 11.5 — Advanced BI & Visualization Studio

This upgrade installs on top of **Upgrade 11**. Existing `/app` React routing, `/legacy-app` original UI link, Qwen3-32B integration, planner fixes, artifacts and Python analytics remain untouched. It requires no additional npm packages beyond your existing React/Recharts dependencies. All visualization requests are **read-only** and involve **zero Hugging Face model calls**.

## What's new

- Navigation: **Visualization Studio** in the left sidebar and command search (`Cmd/Ctrl K`), also linked from AI Insights and the Home Intelligence section.
- Five business sections: Spending, Risk & Anomalies, Savings & Forecasts, Data Quality, and Comparisons.
- Eleven chart families: vertical bar, horizontal bar, line, area, donut, treemap, stacked bar, heatmap, scatter, waterfall, and box plot. The box plot describes **monthly aggregated spending totals**, never raw invoice distributions.
- Each chart only offers compatible graph types. Charts require actual saved analytics; unsupported charts are hidden and replaced with an explanation.
- Coordinated filters across supplier, category, department and month using a privacy-safe cohort endpoint. The same filter settings apply to each visible chart. Clicking a compatible supplier/category chart can drill down.
- Chart CSV and SVG/PNG downloads, full-screen view, table view, and section CSV exports.
- Save up to 12 named dashboard configurations per run in browser storage; export view configuration to JSON. Views are **browser-local**, not yet synchronized across devices. Clearing browser storage deletes the saved configurations, not original report artifacts.

## Privacy and evidence

The new `GET /runs/{run_id}/visualization-cube` endpoint uses the existing authenticated run-reader permission and only completed runs. It does not return raw CSV rows, invoice identifiers, names of requesters, or arbitrary columns. Only semantically approved dimensions and groups with **at least two transactions per four-dimensional cohort** are eligible. The payload contains at most 240 released cohorts. Requests to other organizations' runs are rejected by the existing run access policy.

For privacy, filtered charts **exclude** suppressed small cohorts and show subtotals for eligible groups only. The UI labels these as partial filtered coverage and does not compare them against complete saved totals. Original unfiltered full-run figures come from the saved KPI artifact, not the new endpoint. Where a local CSV is unavailable or too large, the UI can still show saved KPI charts, but fine-grained filtering is unavailable. If the underlying dataset has changed (detected by row count or total spend), the cross-dimensional endpoint refuses the request. This is a basic integrity check, **not a cryptographic file snapshot**; production deployments should store a complete source fingerprint at execution time.

The read-only endpoint currently works with authorized local CSV datasets under `examples/` or managed artifact storage. It does not query Snowflake or S3, and it does not add a new raw-data connector.

## Install

Stop the FastAPI development server, then download `AEAI-Upgrade115-Apply.py` to `~/Downloads`.

```sh
cd ~/projects/autonomous-enterprise-ai-os
source .venv/bin/activate
python3 ~/Downloads/AEAI-Upgrade115-Apply.py --check
python3 ~/Downloads/AEAI-Upgrade115-Apply.py
AEAI_DYNAMIC_REASONING_ENABLED=false AEAI_REASONING_FOLLOWUPS_ENABLED=false python -m pytest -q tests/test_upgrade115_visualization_studio.py
```

On Apple Silicon ensure native Node is selected before building:

```sh
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
node -p 'process.arch'
npm --prefix frontend run build
```

The architecture should be `arm64`. Start your original persistent backend (retaining your own Hugging Face settings) with `bash scripts/start_persistent_local.sh`, then navigate to `http://127.0.0.1:8000/app/visualizations`.

## Troubleshooting

- **Conflicts on `--check`:** Your local file differs from the expected Upgrade 11 version. Do not force; share the file so changes can be merged.
- **No charts:** Select a completed run containing a saved KPI artifact; unsupported chart categories deliberately stay empty.
- **No filters:** The completed run may have no eligible four-dimensional cohorts or the data source may not be an accessible local CSV.
- **Image export misses styling:** SVG and PNG snapshots preserve rendered SVG geometry. Browser-specific CSS may require manual adjustment in exported images; CSV is always available for numeric values.
- **Rollback:** `python3 ~/Downloads/AEAI-Upgrade115-Apply.py --rollback` restores the installer-created backup, as long as installed files have not subsequently been modified.

## Verification limits

Offline Python security and API tests and TypeScript syntax checks are included. A full TypeScript + Vite build must be performed on the user's Mac, because the build environment that produced the patch does not have the project's npm packages. No paid model-backed workflow run is required to verify installation.

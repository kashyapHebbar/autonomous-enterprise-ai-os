# Report Design Upgrade — Executive HTML Reports & Dashboards

This release redesigns **generated output artifacts**, not the business analytics calculations.

## What changes

- New `visualization/premium.py`: self-contained printable HTML template for procurement and generic datasets.
- Upgraded HTML chart artifacts: responsive layouts with real SVG trend lines, spend bars, anomaly tables, risk tables, data roles and provenance.
- Upgraded HTML dashboard artifacts: dedicated KPI cards, visual insights, performance breakdown, forecast and review sections.
- `ReportAgent` now creates **both** its original Markdown report and an executive HTML report; both are `ArtifactType.REPORT` with `metadata.format` set to `markdown` or `html` and proper content types.
- `EvaluationAgent` explicitly chooses the Markdown report for existing deterministic quality checks.
- React `Reports & Artifacts` features HTML reports and dashboards, with filtering, downloads, and clear output descriptions.
- No third-party CDN or inline executable JS is required to render the HTML; static SVG is generated using saved analytics data.

## Usage

1. Stop `make dev` (editing Python source with auto-reload enabled will restart your in-memory repository).
2. Run the provided installer in the existing repository root.
3. Run `source .venv/bin/activate && python -m pytest -q tests/test_report_design_upgrade.py`.
4. Run `python -m pytest -q` to check all existing workflows.
5. Run `cd frontend && npm run build && cd ..` to compile the updated frontend.
6. Start `make dev` and run a *new* procurement or sales workflow.
7. Open `/app/artifacts`; the polished HTML edition is featured. Open it in a new tab. Browser print (⌘P) produces a printer-friendly output that can be saved to PDF.

## Compatibility & limitations

- Old artifact contents are not silently changed. Re-run analysis to generate the new HTML edition.
- Existing source Markdown is retained for evaluator, API and archive compatibility.
- Charts use the available statistics; they do not invent unavailable measures.
- Anomaly risk scores, confidence and savings estimates remain deterministic heuristics.
- Browser links open same-origin artifact content in a new tab; FastAPI must be running and the appropriate artifact permissions must be granted.
- This upgrade does not add a programmatic PDF export endpoint, a live chart editor, or PDF generation libraries.
- In local in-memory mode, restarting FastAPI discards run metadata even when generated artifact files remain on disk.

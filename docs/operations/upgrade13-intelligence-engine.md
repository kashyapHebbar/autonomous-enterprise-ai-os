# AEAI Upgrade 13 — Measured Intelligence & Independent Verification

This is a focused reliability-and-evidence release on top of Upgrade 12.5 plus Operations UI V2. **No Hugging Face API request occurs during installation, benchmarking or verification.** It preserves the existing bounded Qwen investigation, AI cost guard, FastAPI `/app` basename, and both managed workers.

## Included changes

- Every **new managed workflow** attempts a *read-only*, streaming source-to-KPI check after its successful analytics execution. It checks row counts, valid amount rows, procurement spending total, supplier/category counts and full supplier/category spending breakdowns. It records a durable event without changing the underlying report or triggering model inference.
- A run can be `verified`, `mismatch`, `skipped`, or `unavailable`. The workflow may be completed even if this independent audit indicates a mismatch. **Do not treat completed as verified**; inspect the separate verification panel.
- Source-to-KPI verification is supported for **local procurement CSVs** only. Generic analysis, remote URLs, warehouse inputs, and source sizes exceeding `AEAI_AUDIT_MAX_ROWS` are explicitly marked skipped; this is not silent success. Default audit cap: **500,000** rows; allowed 1 to 2,000,000.
- The homepage's **Intelligence performance** panel displays recorded audit counts, total rows scanned in completed source checks, and measured job duration where available; no fake accuracy percentage or rolled-up dollar amount.
- A new **Independent financial verification** panel appears on completed workflow pages. New read-only, workspace-scoped APIs: `/performance/summary` and `/performance/runs/{run_id}/verification`.
- An early conservative **96 MiB CSV input size guard** prevents the existing eager analysis pipeline from unknowingly loading very large files into memory. Set `AEAI_MAX_SOURCE_CSV_MIB` to 1–1024 if you have benchmarked the actual hardware; this does not itself make the pipeline streaming.
- The offline `scripts/benchmark_dataset.py` measures **CSV streaming read only**. It does not measure full workflow inference, forecast, or anomaly speed. For full workloads, compare job completion duration recorded by the backend.

## One-shot installation

Download `AEAI-Upgrade13-Apply.py` into Downloads. From your **existing** project directory:

```bash
cd ~/projects/autonomous-enterprise-ai-os
source .venv/bin/activate
python3 ~/Downloads/AEAI-Upgrade13-Apply.py --check
python3 ~/Downloads/AEAI-Upgrade13-Apply.py
AEAI_DYNAMIC_REASONING_ENABLED=false AEAI_REASONING_FOLLOWUPS_ENABLED=false python -m pytest -q tests/test_upgrade13_intelligence_engine.py
```

Build the UI using the Apple Silicon native Node:

```zsh
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
npm --prefix frontend run build
```

Start your usual **unified** stack with `make dev`. Do not start independent workers unless intentionally debugging; Upgrade 12.5 still manages both.

## Benchmark DC government data without Hugging Face

```bash
python scripts/benchmark_dataset.py examples/government/dc_purchase_card_10k.csv --max-rows 10000
python scripts/benchmark_dataset.py examples/government/dc_purchase_card_50k.csv --max-rows 50000
python scripts/benchmark_dataset.py examples/government/dc_purchase_card_100k.csv --max-rows 100000
```

Run only for files that actually exist. The reported traced Python memory excludes OS file-cache and third-party native allocations. Reconcile dashboard results against source-derived totals and data semantics; a flagged transaction is not proof of fraud.

## Reliability and security

- Authentication and organization/workspace checks are applied on both new APIs.
- No raw CSV rows, vendor names or secrets are included in reconciliation API output.
- No server command endpoint is added; the monitoring scheduler and workflow worker remain server-managed.
- No automatic replay or risk-bearing action; records of failed source checks remain visible for authorized review.
- If the CSV changes after a report is generated, a mismatch is a safety signal, not an invitation to rewrite the report.
- The installer creates a verified rollback snapshot and refuses unexpected local edits. Running `--check` makes no changes.

## Deliberate limitations

**This release does not implement fully streaming anomaly detection or forecasting.** The existing analysis still loads the dataset into memory. It also does not add arbitrary autonomous agent tools, dynamic code execution, cancellation of in-flight jobs, or industrial-scale Snowflake ingestion. These require separate performance and safety work. Existing governed Qwen follow-up reasoning and call-budget enforcement remain enabled through your prior environment settings.

# Upgrade 14 — Big Data Explorer (streaming financial overview)

The existing 6-agent workflow, source profiling and anomaly detection remain
memory-intensive for large files. **This upgrade does not claim to make those
agents million-row safe.** It adds a separate, governed, read-only streaming
financial overview that can process considerably larger local CSVs while using
bounded memory for groups and avoiding materialized transaction lists.

## What is calculated (full source)

- Row count, valid amount count, invalid/missing amounts and missing cells
- Total recorded spending via Python Decimal without exchange-rate conversion
- Supplier and category sums and counts (all groups are included in reconciliation)
- Monthly spending from valid parsed dates
- Source stability check and measured wall time
- Only top 20 groups with >=2 valid transactions returned to the browser

The dashboard does not receive transaction rows or raw invoice IDs.
**No** anomaly counts, duplicate invoices, fraud findings, supplier-risk scores,
forecasting or estimated savings are computed by the streaming overview.
These remain in the ordinary, smaller-data full-fidelity investigation.

## UI and API

Choose **Big Data Explorer** under Manage, or open `/app/scale`.
Select any saved investigation with a local procurement-style CSV and click
**Calculate financial overview**. The API endpoints are:

- `GET /scaling/runs/{run_id}/financial-overview` — last saved overview
- `POST /scaling/runs/{run_id}/financial-overview` — explicit full-file scan,
  requiring run mutation permission

Results are saved as run events and survive restart when the SQL repository is
enabled. Results are bound to the run's tenant/workspace. A single in-process
scan semaphore reduces accidental concurrent work. The scan runs in a request
thread, subject to time/row/file and grouping limits. A reverse proxy may time
out on very large sources; this is not an asynchronous resumable scan.

## Limits

- `AEAI_SCALING_MAX_ROWS=1000000` (max 5 million)
- `AEAI_SCALING_MAX_MIB=512` (max 4096)
- `AEAI_SCALING_MAX_GROUPS=50000` (max 500k)
- `AEAI_SCALING_MAX_SECONDS=120` (max 1800)

Exceeding a limit aborts without returning misleading partial results. Very
high supplier cardinality still increases memory use. These bounds are safety
controls, not performance guarantees for any laptop.

## Benchmark locally (no LLM requests)

```bash
python scripts/benchmark_scalable_csv.py examples/government/dc_purchase_card_10k.csv
```

This reports rows per second, elapsed time and peak Python allocated memory.
It does not measure total process RSS or full six-agent workflow memory.

## Why this is not the final scaling upgrade

Full-fidelity anomalies require cross-row statistics, duplicates and
supplier baselines. Accurate scalable implementation requires disk-backed
indexes/checkpoints or bounded external compute and separate verification.
We intentionally did **not** replace uncomputed risk checks with zeros.
Queued-job cancellation, resumable processing and parallel full analytics are
future work, not implied by this installation.

All operations use the current local CSV and consume **zero** Hugging Face
credits. The original source file is never modified.

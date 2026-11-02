# Upgrade 12 — Autonomous Intelligence Monitoring

This upgrade is **opt-in** and designed for a single-developer local workspace.
Its monitoring control plane is persisted in SQLite independently of the SQLAlchemy run repository.
It does not require an open browser. By default, scheduled jobs use deterministic analytics and make **no Hugging Face calls**.

## Implemented

- `GET /monitoring/summary`, monitor create/list/enable/pause/manual trigger/history, alert list/acknowledge/resolve.
- Workspace-scoped authorization: monitor creation/actions need `runs:write`, reads need `runs:read`.
- Persisted schedules (`hourly`, `daily`, `weekly`, measured relative to activation; not wall-clock cron).
- Atomic SQLite job claiming with `BEGIN IMMEDIATE`; two worker processes cannot claim the same scheduled dispatch.
- Enabled monitors automatically start at their next due time; manual `Run check` queues the next poll and bypasses unchanged-file skipping.
- A separate worker executable independent of Uvicorn/React; worker heartbeat is displayed in the UI.
- Registered **local CSV/TSV** sources and **allowlisted AWS S3 CSV/TSV objects** (optional boto3). Files are read only and limited to 50 MB.
- Approved deterministic analytics produce saved workflow runs and verified aggregate alerts: anomaly count, completeness, and change in total spending between runs **of the same monitor**.
- Saved alert review state, history, source workflow links, run comparison and risk notifications on the homepage.
- Optional extra HF call **only** after a triggered alert and **only** with two separate opt-ins: the monitor's own `AI escalation` toggle and `AEAI_MONITOR_AI_ESCALATION_ENABLED=true` on BOTH API and worker processes. Uses compact aggregate evidence, one call, and the existing monthly cost ledger. Failing HF does not suppress deterministic alerts.
- Skips unchanged local/S3 objects by content SHA-256 when enabled. No inference calls for dashboard viewing, worker idle polls, or tests.

## Install and run (Mac M1)

1. From the project root, run `python3 ~/Downloads/AEAI-Upgrade12-Apply.py --check`, then install with `python3 ~/Downloads/AEAI-Upgrade12-Apply.py`.
2. `AEAI_DYNAMIC_REASONING_ENABLED=false AEAI_REASONING_FOLLOWUPS_ENABLED=false python -m pytest -q tests/test_upgrade12_monitoring.py`.
3. Run native Apple Silicon Node via `eval "$(/opt/homebrew/bin/brew shellenv)"` then `npm --prefix frontend run build`.
4. **Backend terminal:** `bash scripts/start_persistent_local.sh` (keep running).
5. **Second terminal:** activate your venv (`source .venv/bin/activate`), then `bash scripts/start_monitoring_worker.sh` (keep running). For one-off checks, use `bash scripts/monitoring_once.sh` instead.
6. Open `http://127.0.0.1:8000/app/monitoring`. Create a monitor from a registered CSV source. It is **paused by default**; enable it explicitly. The worker will process it in ~30 seconds. Review alerts and the generated saved investigation.

Persistent local files:

- `artifacts/aeai-local-runs.db` — existing SQLAlchemy run repository.
- `artifacts/aeai-local-sources.json` — existing local source catalog.
- `artifacts/aeai-monitoring.db` (+ WAL files) — monitoring control plane and alerts.
- `artifacts/monitor-inputs/` — **sensitive** read-only snapshots downloaded from allowlisted S3. Back up securely and clean up according to your data retention policy.
- `artifacts/llm_usage.jsonl` — existing conservative AI usage ledger.

## Optional AWS S3 monitoring

Install boto3 if not already installed: `python -m pip install 'boto3>=1.34,<2'`.
Configure the **same** allowlist on the backend and worker:

```bash
export AEAI_MONITOR_S3_ALLOWED_BUCKETS=my-approved-readonly-bucket
```

Use an IAM profile/role with `s3:GetObject` and (if scoped by your policy) `s3:ListBucket` as needed; no PutObject, DeleteObject or bucket write permission is used by this feature. Configure AWS authentication via your normal profile/role, **never** in the web dashboard. Create a monitor with a direct `s3://my-approved-readonly-bucket/prefix/transactions.csv` source.

The worker reads object metadata, fetches at most 50 MB, stores a restricted local snapshot, and executes the same deterministic workflow. Standard S3 read/request charges may apply independently of HF inference.

## Optional governed HF alert explanations

Default: **disabled**. To allow a user to opt in per monitor, export this **on both backend and worker terminals**:

```bash
export AEAI_MONITOR_AI_ESCALATION_ENABLED=true
```

The **worker** additionally needs a valid `HF_TOKEN` passed as an environment variable. The ordinary scheduled workflow stays deterministic and free of inference; only a triggered alert may request one short explanation. The shared budget ledger applies and charges depend on the HF provider. No automatic purchasing, decision execution, account changes or remediation are performed.

## Safety / deliberate scope

- No background worker starts automatically from the web server; the separate worker must stay running. This avoids duplicated scheduled jobs under Uvicorn reload or multiple web workers.
- A claimed job is **at most once**. On crash, an in-progress dispatch is left visible for manual review; no blind retry, no duplicate money spend. For production, add a supervised worker and operator-controlled recovery.
- Only the *latest completed check for the same monitor* is a baseline for spending-change alerts; a first run never claims a trend change without a baseline.
- Existing SQLite/Snowflake warehouse connectors remain available for **manual** read-only analyses, but **scheduled warehouse monitoring is not included yet** because their connection profiles need persistent credential-safe configuration. Direct S3 support is included via an allowlisted adapter.
- Alerts are suggestions to investigate, not conclusions of wrongdoing. Nothing is emailed or posted to third-party apps. Browser in-app alerting is included.
- Not a production multi-tenant scheduler/HA service; local workspace security settings must be hardened before hosting externally.
- Cost controls are estimates, not HF account spending limits; pre-paid HF billing is authoritative.

To roll back: `python3 ~/Downloads/AEAI-Upgrade12-Apply.py --rollback`, with `make dev` and the worker stopped. Your monitoring DB and saved artifacts are preserved separately; rollback only restores code.

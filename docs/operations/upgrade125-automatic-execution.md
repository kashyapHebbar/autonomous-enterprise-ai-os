# Upgrade 12.5 — Unified execution and Operations Center

## What changed

The frontend never launches OS commands. It submits authenticated, governed
FastAPI requests. Three backend processes fulfill those requests:

1. FastAPI serves the UI and accepts investigation, data-source, Q&A, dashboard,
   monitoring and approval actions.
2. The workflow worker continuously claims queued jobs from the **same** durable
   repository and writes progress, results, and exceptions.
3. The monitoring worker checks enabled schedules and records alerts. Scheduled
   model calls remain disabled unless separately approved and configured.

`/operations/status` reports **workspace-scoped** queued jobs and live local
workflow-worker state. The Operations Center reuses authenticated run retry
endpoints and the existing monitoring controls. Neither API nor browser can
execute arbitrary shell commands or expose environment secrets.

## One terminal on your Mac

Stop prior `make dev` / workflow / monitoring processes to avoid duplicate
workers and port collisions. In your existing Python venv run:

```bash
cd ~/projects/autonomous-enterprise-ai-os
bash scripts/start_persistent_local.sh
# or simply: make dev
```

Both `make dev` and `scripts/start_persistent_local.sh` call
`scripts/launch_ai_os.py` and manage all three processes. For rare
API-only debugging, `make dev-api-only` retains hot reload but does **not**
start workers.
Only this terminal needs HF_TOKEN for interactive workflows; the monitoring
worker forcibly disables model calls. Existing queued jobs in
`artifacts/aeai-local-runs.db` can be picked up automatically. The browser can
be closed while the process is running, but the Mac must remain awake.

To configure Hugging Face, set `HF_TOKEN`, `AEAI_LLM_ENABLED=true`, and model
settings **before** launch. To run without paid inference, use
`AEAI_LLM_ENABLED=false`.

Open `/app/operations` to inspect worker status, pending jobs, and retry a
**dead-letter** job with an audit reason. Retry is not an automatic repeat:
re-running a job may incur charges. Do not click Retry unless the original
failure has been inspected and the underlying cause resolved.

## Deployment

**Deployment does not start Python subprocesses from web requests.** Configure
three managed services from the same immutable release, with shared repository,
artifact storage, and credentials:

| Service | Entrypoint |
|---|---|
| API | `uvicorn aeai_os.api.app:create_app --factory --host 0.0.0.0 --port 8000` |
| Workflow worker | `python scripts/managed_workflow_worker.py` |
| Monitor worker | `python -m aeai_os.monitoring.worker --loop` |

Do not use local SQLite on separate hosts/ephemeral containers. Use the
existing Postgres/Redis queue configuration for the workflow engine, shared
artifact storage, secure secrets, and managed service restart policies. The
monitoring scheduler from Upgrade 12 uses a SQLite control plane; **it needs a
shared persistent single-host volume or a migration to a distributed monitor
store before multi-host production deployment**. The local heartbeat file is
also single-host; in distributed deployments use orchestrator liveness or a
shared monitoring service, not a local-file online signal.

A single process per monitoring database avoids duplicated schedule dispatch.
Service logs and health monitoring are the hosting platform's responsibility.
There is intentionally no API for running migrations, installing plugins,
executing scripts, changing credentials, or deploying new code.

## Recovery

The worker automatically claims queued tasks. Stale claimed jobs are not
silently replayed: inspect statuses before an explicit retry. For monitoring,
use the existing Enable/Pause/Run check buttons. Restore backups and apply
schema migrations using your deployment pipeline, not a publicly accessible
browser command endpoint.

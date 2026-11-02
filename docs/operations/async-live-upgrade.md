# Asynchronous dynamic execution and live progress (Upgrade 1)

- New `POST /runs/{run_id}/execute/async`: returns a queued job (`202`) immediately; rejects missing data (400) or already-started runs (409).
- Existing `/runs/{id}/execute` and procurement endpoints are unchanged.
- New `GET /runs/{run_id}/stream`: authorized SSE snapshots of persisted run, nodes, jobs and event count; no fabricated progress.
- The React composer uses the async endpoint; Workflow Detail subscribes to SSE and keeps polling as fallback.
- Local `AEAI_RUN_REPOSITORY_BACKEND=memory`: the API processes queued jobs via a FastAPI background task in the **same process**. Keep a single API worker; data and running jobs are lost on process restart/reload. No Redis or extra worker is necessary for this local mode.
- SQLAlchemy mode: a **separate** worker is required (example below). The API only queues; it does not execute queued jobs in-process.
- Dynamic job `max_attempts=1` for now: automatic replay of a partially executed graph could duplicate side effects. Do not enable blind retries until execution is idempotent.
- Existing procurement workflow continues through the original worker path.
- Approval-waiting run is considered the end of that worker job; approval resumes through the existing API (currently synchronous).
- Cancellation, safe resumable distributed execution, independent heartbeats during long jobs, and token-authenticated SSE requiring custom authorization headers are **not** implemented yet. They are subsequent milestones.

## Local quick start

```bash
source .venv/bin/activate
cd frontend && npm install && npm run build && cd ..
make dev
```

Open `http://localhost:8000/app` and create a procurement or sales workflow. For the local memory configuration the browser sees queued/running/completed statuses as the background task executes.

## Durable worker mode (optional)

Configure the API and worker with matching `AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy`, `AEAI_DATABASE_URL`, `AEAI_WORKFLOW_QUEUE_BACKEND=repository` (or `redis`, with matching Redis settings), and shared artifact storage. Start the API, and in a separate terminal:

```bash
source .venv/bin/activate
python scripts/run_workflow_worker.py --loop --poll-interval 1
```

Do not use separate worker processes with the in-memory repository, because they cannot share state.

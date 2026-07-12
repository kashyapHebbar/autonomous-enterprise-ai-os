# Autonomous Enterprise AI Operating System

An MVP for a durable multi-agent workflow platform where specialized AI agents collaborate on
enterprise analytics tasks.

The first vertical slice is a procurement analytics workflow:

1. A user submits a request and dataset.
2. A planner agent creates an execution graph.
3. Data, analytics, visualization, report, evaluation, and security agents execute the graph.
4. The platform stores run state, artifacts, evaluation results, and observability traces.
5. The user receives a dashboard/report with linked provenance.

## What It Demonstrates

- Planner-generated execution graphs with typed nodes and dependencies
- Repository-backed run state, checkpoints, artifacts, events, and evaluations
- Warehouse dataset references through SQLite and Snowflake connector abstractions
- Data retrieval, analytics/code, visualization, report, and evaluation agents
- Security policy gates for required tools and risky actions
- API-driven workflow execution, approval decisions, failed-node retry, and run inspection
- OpenTelemetry trace IDs, Prometheus-compatible metrics, and optional MLflow/LangSmith tracking
- Docker Compose for API, workflow worker, Postgres, Redis, and MinIO
- Kubernetes baseline manifests for API, worker, local dependencies, probes, and observability

## Architecture

```mermaid
flowchart LR
    User[User request] --> Planner[Planner agent]
    Planner --> Orchestrator[Orchestrator]
    Orchestrator --> Data[Data retrieval agent]
    Data --> Analytics[Analytics/code agent]
    Analytics --> Viz[Visualization agent]
    Viz --> Report[Report agent]
    Report --> Eval[Evaluation agent]
    Orchestrator --> Security[Tool permission policy]
    Orchestrator --> Obs[Traces and metrics]
    Data --> Artifacts[Artifact store: local / S3-compatible]
    Analytics --> Artifacts
    Viz --> Artifacts
    Report --> Artifacts
    Eval --> Artifacts
```

## Quick Start

Requirements: Python 3.11 or newer.

```bash
git clone https://github.com/kashyapHebbar/autonomous-enterprise-ai-os.git
cd autonomous-enterprise-ai-os
python3.11 -m venv .venv
source .venv/bin/activate
make install
make smoke
make test
```

Run the API:

```bash
make dev
```

Open:

- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Metrics: [http://127.0.0.1:8000/metrics](http://127.0.0.1:8000/metrics)

## Procurement Demo

The demo uses `examples/procurement_demo.csv` and writes generated artifacts under
`artifacts/procurement_demo/<run_id>/`.

```bash
make demo
```

Expected output includes a run ID, trace ID, generated dashboard path, report path, evaluation
artifact path, metrics file, and `demo_summary.json`.

You can pass a different dataset while keeping the same workflow:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_procurement_demo.py \
  --dataset examples/procurement_demo.csv \
  --artifact-root artifacts/procurement_demo
```

The generated summary records:

- Run status and trace ID
- Dataset path
- Dashboard, report, evaluation, KPI, chart, and code artifacts
- Evaluation pass/fail score and checks
- Event count and Prometheus-compatible metrics path

## API Routes

Authentication is disabled by default for local demos. When `AEAI_AUTH_ENABLED=true`, `/runs`
endpoints expect `X-AEAI-User-Id`, optional `X-AEAI-User-Name`, and `X-AEAI-Roles` headers.
Supported roles are `viewer` for read-only inspection, `operator` for run and artifact mutations,
`approver` for approval decisions, and `admin` for all current capabilities. Mutating API actions
write `audit` events with actor identity under `/runs/{run_id}/events`.

| Route | Purpose |
| --- | --- |
| `POST /runs` | Create an agent workflow run |
| `GET /runs/{run_id}` | Inspect run state, artifacts, evaluations, and trace ID |
| `POST /runs/{run_id}/datasets/reference` | Attach an external dataset reference |
| `POST /runs/{run_id}/datasets/upload` | Upload a local dataset file |
| `POST /runs/{run_id}/execute/procurement` | Execute the procurement workflow synchronously |
| `POST /runs/{run_id}/execute/procurement/async` | Queue the procurement workflow |
| `GET /runs/{run_id}/workflow-jobs` | Inspect queued workflow jobs |
| `POST /runs/{run_id}/deployments` | Request approval to promote artifacts |
| `POST /runs/{run_id}/deployments/{job_id}/approval` | Approve or deny a deployment request |
| `GET /runs/{run_id}/graph-nodes` | Inspect execution graph node state |
| `GET /runs/{run_id}/events` | Inspect agent event telemetry |
| `GET /runs/{run_id}/timeline` | Inspect chronological run activity |
| `POST /runs/{run_id}/graph-nodes/{node_id}/approval` | Approve or deny a waiting graph node |
| `POST /runs/{run_id}/graph-nodes/{node_id}/retry` | Retry a failed graph node |
| `GET /runs/{run_id}/evaluations` | List evaluation results for a run |
| `GET /run-inspector/runs/{run_id}` | Browser run inspector UI |
| `GET /metrics` | Prometheus-compatible run and agent metrics |
| `GET /health` | Service health |
| `GET /docs` | Interactive OpenAPI documentation |

## Warehouse Dataset References

The procurement workflow supports local CSV files, SQLite-backed warehouse references for offline
tests and demos, and Snowflake-backed references when the optional warehouse dependency is installed
and `SNOWFLAKE_*` settings are configured. `SqliteWarehouseConnector` and
`SnowflakeWarehouseConnector` provide table/query execution through the same adapter contract used by
analytics agents.

Dataset artifacts can be marked as warehouse-backed with URIs such as
`sqlite:///absolute/path/to/warehouse.db#procurement` or
`snowflake://ANALYTICS/PUBLIC/PROCUREMENT` plus metadata `{"source": "warehouse"}`. Query references
can pass bind values through metadata `query_parameters` so previews and full extraction paths remain
parameterized.

Install Snowflake support with:

```bash
pip install ".[warehouse]"
```

Required Snowflake environment variables:

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER`
- `SNOWFLAKE_PASSWORD`
- `SNOWFLAKE_WAREHOUSE`
- `SNOWFLAKE_DATABASE`
- `SNOWFLAKE_SCHEMA`

Optional controls include `SNOWFLAKE_ROLE`, `SNOWFLAKE_CONNECT_TIMEOUT_SECONDS`,
`SNOWFLAKE_QUERY_TIMEOUT_SECONDS`, `SNOWFLAKE_ROW_LIMIT`, and `SNOWFLAKE_APPLICATION`.
The connector validates unquoted identifiers, blocks unsafe statements, applies query timeouts and a
maximum row limit, and local tests use a mocked connection factory so no real credentials are needed.

## Artifact Storage

Run artifact metadata is stored in the run repository, while payloads are written through an
artifact store. Local filesystem storage remains the default for development and demos. Set
`AEAI_ARTIFACT_STORAGE_BACKEND=s3` to write generated datasets, schema profiles, KPI JSON, charts,
reports, and evaluations to an S3-compatible backend such as AWS S3 or MinIO.

Install object storage support with:

```bash
pip install ".[storage]"
```

S3-compatible settings:

- `AEAI_ARTIFACT_S3_BUCKET`
- `AEAI_ARTIFACT_S3_PREFIX`
- `AEAI_ARTIFACT_S3_ENDPOINT_URL`
- `AEAI_ARTIFACT_S3_REGION`
- `AEAI_ARTIFACT_S3_ACCESS_KEY_ID`
- `AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY`

Artifact records retain stable URIs such as local file paths or `s3://bucket/key` plus durable
storage metadata fields for backend, key, content type, and payload size. Source artifact IDs and
producer node IDs are persisted so lineage remains available after API restarts.

## Run With Docker Compose

```bash
docker compose up --build
```

The local stack includes the API, Postgres, Redis, and MinIO.
It also includes a `workflow-worker` service that continuously claims queued procurement jobs.

Run the procurement workflow through the local API:

```bash
RUN_ID=$(curl -s -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task":"Analyze this procurement dataset and create a dashboard report.","dataset_uri":"examples/procurement_demo.csv"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -X POST "http://127.0.0.1:8000/runs/${RUN_ID}/execute/procurement"
curl "http://127.0.0.1:8000/runs/${RUN_ID}"
```

Open `http://127.0.0.1:8000/run-inspector/runs/${RUN_ID}` to inspect graph nodes,
events, artifact lineage, approval history, evaluation/MLflow status, deployment history, and
approve/deny or retry actionable nodes.

## Kubernetes Baseline

Validate the Kubernetes manifests locally:

```bash
make k8s-validate
```

The baseline in `deploy/kubernetes/` includes the API, workflow worker, Postgres, Redis, MinIO,
config, secrets, services, health probes, and observability environment variables. See
[deploy/kubernetes/README.md](deploy/kubernetes/README.md) for kind/minikube deployment and teardown
steps.

With RBAC enabled, include an actor and role header:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -H "X-AEAI-User-Id: operator-1" \
  -H "X-AEAI-Roles: operator" \
  -d '{"task":"Analyze this procurement dataset and create a dashboard report."}'
```

Queued workflow execution defaults to the repository-backed queue. Set
`AEAI_WORKFLOW_QUEUE_BACKEND=redis` to use Redis as the pending-job broker while keeping the run
repository as the authoritative execution guard. Workers heartbeat claimed jobs, recover timed-out
claims, retry according to `max_attempts`, and move exhausted jobs to `dead_letter`.

## Database Migrations

Persistent run storage uses Alembic migrations. The API can still create tables automatically for
local demos with `AEAI_RUN_REPOSITORY_CREATE_SCHEMA=true`, but shared or deployed databases should
be initialized explicitly:

```bash
AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@localhost:5432/aeai_os make db-upgrade
AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@localhost:5432/aeai_os make db-validate
```

For a CI-friendly local check against SQLite:

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_database.py \
  --database-url sqlite+pysqlite:///./tmp-platform.db upgrade
PYTHONPATH=src .venv/bin/python scripts/manage_database.py \
  --database-url sqlite+pysqlite:///./tmp-platform.db validate
```

## Documentation

- Architecture: [docs/architecture.md](docs/architecture.md)
- Development guide: [docs/development.md](docs/development.md)
- Kubernetes baseline: [deploy/kubernetes/README.md](deploy/kubernetes/README.md)

## Tests

```bash
make lint
make test
make smoke
make demo
make k8s-validate
```

GitHub Actions runs this same validation sequence on pull requests and pushes to `main` after
installing development dependencies with `make install`.

The regression suite covers:

- API and health behavior
- Run repository behavior for in-memory and SQLAlchemy-backed storage
- Procurement demo completion with dashboard, report, evaluation, trace metadata, and metrics

### Trace Export

Tracing is enabled locally without exporting spans by default. Set `AEAI_TRACE_EXPORTER=console`
to print spans during development, or use `AEAI_TRACE_EXPORTER=otlp_http` /
`AEAI_TRACE_EXPORTER=otlp_grpc` with `AEAI_OTEL_EXPORTER_OTLP_ENDPOINT` in deployed environments.
Install `.[observability]` when exporting to an OTLP collector, MLflow, or LangSmith.

MLflow tracking is disabled by default. Set `AEAI_MLFLOW_TRACKING_ENABLED=true` and
`AEAI_MLFLOW_TRACKING_URI` to mirror evaluation scores, pass/fail state, check metrics, run IDs, and
trace IDs into an MLflow experiment.

LangSmith trace review is disabled by default. Set `AEAI_LANGSMITH_TRACING_ENABLED=true`,
`AEAI_LANGSMITH_API_KEY`, and optionally `AEAI_LANGSMITH_PROJECT` to mirror agent events and
evaluation results into LangSmith with run IDs, trace IDs, graph node IDs, agent names, and artifact
IDs in metadata.

## Current Limitations

- The platform is an actively developed prototype, not a production workflow control plane.
- Connectors and approval policies should be hardened before use with sensitive enterprise systems.
- Generated analysis should be reviewed before business decisions or deployment actions.

## Direction

The next roadmap is deployment approvals and a richer UI for inspecting
execution graphs, artifacts, approval decisions, MLflow runs, and deployment history.

## Responsible Use

This is a prototype platform for local/cloud-ready agent orchestration. Generated analysis should be
reviewed before production use, especially when workflows depend on external data, code execution,
approval decisions, or deployment actions.

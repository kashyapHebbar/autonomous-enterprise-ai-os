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
- Docker Compose for API, Postgres, Redis, and MinIO
- Kubernetes starter manifests in `deploy/kubernetes/`

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
    Data --> Artifacts[Local artifact store]
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

The procurement workflow supports local CSV files and SQLite-backed warehouse references for offline
tests and demos. `SqliteWarehouseConnector` provides table/query execution through the same adapter
contract used by analytics agents, while `SnowflakeWarehouseConnector` validates `SNOWFLAKE_*`
environment settings and keeps Snowflake execution behind parameterized connector calls.

Dataset artifacts can be marked as warehouse-backed with URIs such as
`sqlite:///absolute/path/to/warehouse.db#procurement` or
`snowflake://ANALYTICS/PUBLIC/PROCUREMENT` plus metadata `{"source": "warehouse"}`.

## Run With Docker Compose

```bash
docker compose up --build
```

The local stack includes the API, Postgres, Redis, and MinIO.

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

## Documentation

- Architecture: [docs/architecture.md](docs/architecture.md)
- Development guide: [docs/development.md](docs/development.md)
- Kubernetes baseline: [deploy/kubernetes/README.md](deploy/kubernetes/README.md)

## Tests

```bash
make test
make smoke
make demo
```

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

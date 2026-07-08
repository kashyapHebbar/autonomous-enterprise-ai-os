# Local Development

This project uses a small Python service plus local infrastructure dependencies. The first runnable surface is a health endpoint and repository smoke check.

## Prerequisites

- Python 3.11+
- Docker Desktop or compatible Docker runtime
- Git

On macOS, if `python3.11` is not available, install Python 3.11 first or use the Docker Compose flow. The application and test dependencies require Python 3.11+.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
make install
```

## Run Checks

```bash
make lint
make test
make smoke
make demo
make k8s-validate
```

`make smoke` only uses the Python standard library and verifies the scaffold shape plus the health payload.
`make demo` runs the end-to-end procurement agent workflow and writes generated artifacts under
`artifacts/procurement_demo/<run_id>/`.

GitHub Actions runs the same validation sequence on every pull request and push to `main`.
The CI workflow installs the development dependencies with `make install` and runs the five checks
above.

## Database Migrations

Persistent platform tables are managed by Alembic. The migration wrapper reads
`AEAI_DATABASE_URL`, so the normal Postgres flow is:

```bash
AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@localhost:5432/aeai_os make db-upgrade
AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@localhost:5432/aeai_os make db-validate
```

The same commands work in deployed environments when `AEAI_DATABASE_URL` points at the target
database. For tests or local experiments without Postgres, use SQLite:

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_database.py \
  --database-url sqlite+pysqlite:///./tmp-platform.db upgrade
PYTHONPATH=src .venv/bin/python scripts/manage_database.py \
  --database-url sqlite+pysqlite:///./tmp-platform.db validate
```

Set `AEAI_RUN_REPOSITORY_CREATE_SCHEMA=false` when the API or worker should rely on migrations
instead of creating tables at startup.

## Run The API Locally

```bash
make dev
```

Then open:

- API health: `http://localhost:8000/health`
- API metrics: `http://localhost:8000/metrics`
- API docs: `http://localhost:8000/docs`

## Local Authentication And RBAC

Local development runs without enforced authentication by default. In that mode, mutating run API
calls are audited as the configured local user:

```bash
AEAI_AUTH_LOCAL_USER_ID=local-dev
AEAI_AUTH_LOCAL_USER_NAME="Local Developer"
AEAI_AUTH_LOCAL_ROLES=admin
```

To enforce access controls, set `AEAI_AUTH_ENABLED=true` and send identity headers on `/runs`
requests:

```bash
curl http://localhost:8000/runs \
  -H "X-AEAI-User-Id: viewer-1" \
  -H "X-AEAI-User-Name: Viewer One" \
  -H "X-AEAI-Roles: viewer"
```

Roles map to capabilities as follows:

| Role | Capabilities |
| --- | --- |
| `viewer` | Read runs, jobs, graph nodes, events, timelines, evaluations, artifacts, and lineage |
| `operator` | Viewer access plus create runs, attach/upload datasets, execute workflows, enqueue jobs, and retry failed nodes |
| `approver` | Viewer access plus approve or deny waiting graph nodes |
| `admin` | All current run, mutation, approval, and administrative capabilities |

Every authorized mutating run API request that reaches a handler records an `audit` event containing
the actor id, name, roles, action, target, and timestamp. Inspect those entries with
`GET /runs/{run_id}/events`.

## Run Lifecycle API

Create a run:

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task":"Analyze this procurement dataset and create a dashboard."}'
```

Attach a dataset reference:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/datasets/reference \
  -H "Content-Type: application/json" \
  -d '{"uri":"s3://example/procurement.csv","format":"csv"}'
```

Upload a local dataset:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/datasets/upload \
  -F "file=@data/procurement.csv"
```

Inspect run state and artifacts:

```bash
curl http://localhost:8000/runs/{run_id}
curl http://localhost:8000/runs/{run_id}/artifacts
curl http://localhost:8000/runs/{run_id}/graph-nodes
curl http://localhost:8000/runs/{run_id}/events
curl http://localhost:8000/runs/{run_id}/timeline
```

The browser inspector for the same data is available at
`http://localhost:8000/run-inspector/runs/{run_id}`.
It shows approve/deny controls for nodes and deployment jobs waiting on human
approval, a retry control for failed nodes, inline artifact lineage, approval history,
evaluation/MLflow status, and deployment history.

Execute the procurement workflow for a run with an attached dataset:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/execute/procurement
```

The execution response includes run status, trace ID, completed/failed node IDs,
waiting-for-approval state, artifacts, and evaluations.

Approve or deny a graph node that is waiting on human approval:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/graph-nodes/{node_id}/approval \
  -H "Content-Type: application/json" \
  -d '{"approved":true,"comment":"Approved for local demo."}'
```

Request deployment approval for reviewed artifacts:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/deployments \
  -H "Content-Type: application/json" \
  -d '{
    "artifact_ids":["artifact_dashboard"],
    "destination":"s3://approved-dashboards/procurement",
    "requested_by":"analytics-lead",
    "rationale":"Promote the validated dashboard."
  }'
```

Approve or deny a deployment request:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/deployments/{job_id}/approval \
  -H "Content-Type: application/json" \
  -d '{
    "approved":true,
    "approver":"release-manager",
    "rationale":"Evaluation passed and artifacts were reviewed."
  }'
```

Retry a failed graph node after fixing its input or environment:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/graph-nodes/{node_id}/retry
```

## Procurement Demo

The packaged demo uses `examples/procurement_demo.csv` to run the same planner, orchestrator,
security policy, agents, evaluation gates, and observability path used by the tests.

```bash
make demo
```

The command prints the run ID, trace ID, dashboard artifact, report artifact, evaluation artifact,
metrics path, and summary JSON path. The summary JSON includes run metadata, artifact metadata,
evaluation checks, event count, and the metrics file location.

The CLI and API share the same workflow service in `aeai_os.workflows.procurement`, so `make demo`
and `POST /runs/{run_id}/execute/procurement` exercise the same planner/orchestrator/agent path.

To use another CSV with the same schema:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_procurement_demo.py \
  --dataset /path/to/procurement.csv \
  --artifact-root artifacts/procurement_demo
```

## Kubernetes Baseline

The Kubernetes baseline lives in `deploy/kubernetes/` and is applied as a kustomization:

```bash
make k8s-validate
kubectl apply -k deploy/kubernetes
```

It includes API and workflow worker deployments, local Postgres/Redis/MinIO dependencies, shared
config, a local-development secret template, ClusterIP services, health probes, and observability
environment variables. See `deploy/kubernetes/README.md` for kind/minikube image loading,
rollout checks, port-forwarding, and teardown commands.

## Orchestrator Kernel

The SCRUM-9 orchestration kernel runs validated execution graphs against registered agents and stores each state transition in the run repository.

Current local behavior:

- Multi-step graphs execute in dependency order.
- Run checkpoints persist the LangGraph-compatible state shape.
- Failed nodes retry according to `RetryPolicy` without restarting completed nodes.
- Nodes that return `waiting_for_approval` pause the run until `approve_node` resumes it.
- `POST /runs/{run_id}/execute/procurement/async` persists a workflow job for background
  processing.
- `scripts/run_workflow_worker.py` claims queued procurement jobs, heartbeats ownership, executes
  the workflow, and records completion, retry, timeout recovery, or dead-letter state.
- `POST /runs/{run_id}/deployments` creates a deployment workflow job in
  `waiting_for_approval`; approval completes the job and creates a deployment artifact, while
  denial records a failed deployment outcome.
- `GET /runs/{run_id}/graph-nodes`, `GET /runs/{run_id}/events`, and
  `GET /runs/{run_id}/timeline` expose the graph inspection surface used by the run inspector UI.

The in-memory repository remains the default local checkpoint backend. Set
`AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy` and `AEAI_DATABASE_URL` to use the durable SQLAlchemy
repository against Postgres or SQLite-compatible test databases. The SQLAlchemy backend persists
runs, workflow jobs, graph nodes, artifacts, agent events, evaluations, and checkpoints behind the
same repository contract. `AEAI_RUN_REPOSITORY_CREATE_SCHEMA=true` lets the API and worker create
the repository tables automatically for local, Compose, and demo environments; set it to `false`
when a production database is managed by explicit migrations.

## Distributed Workflow Queue

The workflow queue is configurable through environment variables:

```bash
AEAI_WORKFLOW_QUEUE_BACKEND=repository
AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS=300
AEAI_WORKFLOW_QUEUE_KEY_PREFIX=aeai:workflow
AEAI_REDIS_URL=redis://redis:6379/0
```

`repository` is the default backend for local tests and stores queue state in the configured run
repository. With `AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy`, multiple workers share durable queue
state through Postgres. `redis` uses Redis as the pending-job broker while the repository remains
the authoritative source for claims, retries, dead-lettering, and idempotent completion guards.

Run one worker locally:

```bash
python scripts/run_workflow_worker.py --worker-id local-worker
```

Run continuous polling:

```bash
python scripts/run_workflow_worker.py --loop --worker-id local-worker
```

Docker Compose starts both the API and a continuous worker:

```bash
docker compose up --build
```

To try Redis-backed pending-job fan-out in Compose, set `AEAI_WORKFLOW_QUEUE_BACKEND=redis` in the
environment used by the API and worker. Workers will only complete or fail jobs they own; stale
claims are requeued until attempts are exhausted, then moved to `dead_letter`.

## Artifact Storage

Artifact metadata and artifact payloads are deliberately separate. The run repository stores
`ArtifactRecord` metadata, lineage, type, producer, stable URI, and storage metadata. The
`ArtifactStore` writes and reads the payload bytes used by agents.

Local filesystem storage is the default:

```bash
AEAI_ARTIFACT_STORAGE_BACKEND=local
AEAI_ARTIFACT_ROOT=artifacts
```

Use the S3-compatible backend for AWS S3 or MinIO:

```bash
AEAI_ARTIFACT_STORAGE_BACKEND=s3
AEAI_ARTIFACT_S3_BUCKET=aeai-artifacts
AEAI_ARTIFACT_S3_PREFIX=aeai-artifacts
AEAI_ARTIFACT_S3_ENDPOINT_URL=http://localhost:9000
AEAI_ARTIFACT_S3_ACCESS_KEY_ID=aeai_minio
AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY=aeai_minio_password
```

Install the optional client dependency with `pip install ".[storage]"`. The bucket must already
exist. With Docker Compose, MinIO is available on `http://localhost:9000` and its console is on
`http://localhost:9001`.

Agents read and write generated artifacts through the store, so local paths and `s3://bucket/key`
URIs can both move through the same workflow. Local tests use a fake S3 client, so no cloud account
or MinIO service is required for the regression suite.

## Planner Contract

The SCRUM-10 planner defines a structured execution graph contract that can be produced by a deterministic MVP planner now and by structured LLM output later.

Current planner behavior:

- `PlannerAgent.create_plan` supports the procurement analytics dashboard/report workflow.
- `ExecutionPlanSchema` defines the JSON schema for planner output.
- Each plan node includes agent assignment, dependencies, required tools, expected artifacts, and risk.
- `validate_planner_output` rejects unknown agents, missing dependencies, invalid risk labels, and unknown artifact types with actionable errors.

## Data Ingestion

The SCRUM-11 data retrieval agent supports local CSV ingestion for the procurement MVP.

Current data behavior:

- `profile_csv_dataset` infers column types, missing value counts, duplicate rows, examples, and numeric summary statistics.
- `DataRetrievalAgent` reads a dataset artifact or local dataset URI, writes schema and quality JSON files, and registers them as run artifacts.
- `CsvDatasetAdapter` exposes preview, row access, and grouped sum queries for downstream analytics agents.
- `WarehouseDatasetAdapter` lets connector-backed datasets satisfy the same query contract used by analytics agents.
- `dataset_reference_from_metadata` distinguishes local file datasets from warehouse-backed table or query references.
- `WarehouseConnectorRegistry` resolves warehouse adapters by source metadata or URI scheme.
- `SqliteWarehouseConnector` gives tests and offline demos deterministic preview, schema inspection, grouped aggregate queries, and connector-backed procurement workflow execution.
- `SnowflakeWarehouseConnector` validates `SNOWFLAKE_*` environment settings, applies timeout and row-limit controls, and executes parameterized Snowflake-backed table/query references when the optional warehouse dependency is installed.

Warehouse dataset artifacts can use URI schemes or metadata:

```json
{
  "uri": "sqlite:///absolute/path/to/warehouse.db#procurement",
  "metadata": {"source": "warehouse"}
}
```

```json
{
  "uri": "snowflake://ANALYTICS/PUBLIC/PROCUREMENT",
  "metadata": {"source": "warehouse"}
}
```

SQLite warehouse references can run through data profiling and procurement analytics locally.
Snowflake references use the same adapter contract when `snowflake-connector-python` is installed via
`pip install ".[warehouse]"` and the required `SNOWFLAKE_*` settings are present. Required settings are
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`,
`SNOWFLAKE_DATABASE`, and `SNOWFLAKE_SCHEMA`. Optional settings include `SNOWFLAKE_ROLE`,
`SNOWFLAKE_CONNECT_TIMEOUT_SECONDS`, `SNOWFLAKE_QUERY_TIMEOUT_SECONDS`, `SNOWFLAKE_ROW_LIMIT`, and
`SNOWFLAKE_APPLICATION`.

Snowflake table identifiers are validated as safe unquoted identifiers. Query references must be a
single `SELECT` or `WITH` statement, previews and full row extraction use bind parameters for limits,
and local tests verify execution through a mocked Snowflake connection instead of real credentials.

## Procurement Analytics

The SCRUM-12 analytics/code agent converts the ingested procurement CSV into structured KPIs and a reproducible code artifact.

Current analytics behavior:

- `analyze_procurement_dataset` calculates total spend, supplier/category rankings, monthly trends, transaction outliers, estimated savings opportunities, and missing-data risks.
- `AnalyticsCodeAgent` writes `procurement_analysis.json` and a reproducible Python script, then registers `kpi_table` and `code` artifacts with dataset lineage.
- `PythonCodeGuard` blocks network, process, dynamic execution, and destructive operations before code can be accepted.
- Filesystem writes are classified as `approval_required`; generated source is validated and stored but never dynamically executed in the MVP.

## Procurement Visualization

The SCRUM-13 visualization agent converts structured analytics output into local dashboard artifacts.

Current visualization behavior:

- `VisualizationAgent` resolves the latest `kpi_table` artifact from the run or accepts an explicit `kpi_artifact_id`.
- `build_procurement_chart_specs` creates charts for KPIs, supplier concentration, category breakdowns, monthly trends, and anomalies.
- Each chart is written as a standalone HTML artifact with embedded chart data and lineage back to the KPI artifact.
- `procurement_dashboard.html` is a self-contained local dashboard that embeds the same chart panels and records source artifact IDs for traceability.

## Procurement Reporting

The SCRUM-14 report agent generates the final local report artifact and expands artifact lineage.

Current reporting behavior:

- `ReportAgent` resolves upstream KPI, schema, quality, chart, and dashboard artifacts from the run.
- `ArtifactLineageService` recursively expands source artifact IDs so reports can trace back to the uploaded dataset and producer nodes.
- `procurement_report.md` includes executive summary, key findings, KPIs, dataset quality, chart references, recommendations, assumptions, limitations, and lineage.
- `GET /runs/{run_id}/artifacts/{artifact_id}` retrieves artifact metadata, and `GET /runs/{run_id}/artifacts/{artifact_id}/lineage` returns upstream artifact lineage.

## Procurement Evaluation

The SCRUM-15 evaluation agent scores generated outputs with deterministic quality gates.

Current evaluation behavior:

- `EvaluationAgent` resolves KPI, chart, dashboard, and report artifacts for a run.
- `evaluate_procurement_outputs` checks task completion, artifact completeness, assumptions/limitations disclosure, and KPI total-spend consistency across computed data, report text, and chart JSON.
- Evaluation results are stored as repository records and as `evaluation` artifacts with score, pass/fail, target artifact, and per-check details.
- `GET /runs/{run_id}` includes evaluation results, and `GET /runs/{run_id}/evaluations` lists them directly.
- In the orchestrated workflow, failed required checks return a failed evaluation node so the run becomes visibly failed.

## Security Controls

The SCRUM-16 security layer classifies node tool requirements before an agent executes.

Current security behavior:

- `ToolPermissionRegistry` defines read-only, write, external-network, code-execution, and deployment permission levels.
- `OrchestratorService` evaluates every node `required_tools` entry before calling the agent implementation.
- Low/medium-risk tools are allowed and audited; high-risk tools pause the run until approval; destructive tools are blocked.
- Tool audit events record agent, tool, permission level, risk, input summary, decision, approval state, and timestamp.
- Existing generated Python analysis code still goes through `PythonCodeGuard`, while the orchestrator policy controls graph-level tool permissions.

## Observability

The SCRUM-17 observability layer adds trace IDs, OpenTelemetry spans, evaluation logging, and Prometheus-compatible metrics.

Current observability behavior:

- `RunRecord.trace_id` is populated when a run is created.
- HTTP responses include `x-trace-id` while running through FastAPI.
- API requests, orchestrator execution/resume calls, agent nodes, tool permission decisions, and evaluation logging create OpenTelemetry spans.
- Agent events include `trace_id`, and node completion/failure/approval-pause events include status and duration timing.
- Evaluation results are logged as structured observability events with `backend: opentelemetry`.
- Optional MLflow tracking can mirror evaluation score, pass/fail state, check metrics, run ID, and trace ID when enabled.
- Optional LangSmith trace review can mirror agent events and evaluation results with run ID, trace ID, graph node ID, agent name, and artifact ID metadata when enabled.
- `GET /metrics` exposes run counts, run status totals, error totals, artifact count, evaluation count and average score, node retry totals, run duration totals, and node status counts by agent.
- `AEAI_TRACE_EXPORTER` controls span export: `none` for local trace IDs without export, `console` for local debugging, `otlp_http` for an OTLP/HTTP collector, `otlp_grpc` for an OTLP/gRPC collector, or `disabled` to skip tracing setup.

Local console tracing:

```bash
AEAI_TRACE_EXPORTER=console make dev
```

Collector-backed tracing:

```bash
AEAI_TRACE_EXPORTER=otlp_http \
AEAI_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces \
make dev
```

Install the optional observability dependencies when exporting to OTLP, MLflow, or LangSmith:

```bash
pip install ".[observability]"
```

Local file-backed MLflow tracking:

```bash
AEAI_MLFLOW_TRACKING_ENABLED=true \
AEAI_MLFLOW_TRACKING_URI=file:./artifacts/mlruns \
AEAI_MLFLOW_EXPERIMENT_NAME="Autonomous Enterprise AI OS" \
make demo
```

Server-backed MLflow tracking uses the same switch with a server URI:

```bash
AEAI_MLFLOW_TRACKING_ENABLED=true \
AEAI_MLFLOW_TRACKING_URI=http://localhost:5000 \
make dev
```

LangSmith trace review is disabled locally by default. Enable it by providing an API key and project:

```bash
AEAI_LANGSMITH_TRACING_ENABLED=true \
AEAI_LANGSMITH_API_KEY=lsv2_... \
AEAI_LANGSMITH_PROJECT="Autonomous Enterprise AI OS" \
make demo
```

The LangSmith adapter records agent events and evaluation results as reviewable runs. Metadata includes `aeai.run_id`, `aeai.trace_id`, `aeai.graph_node_id`, `aeai.agent_name`, and `aeai.artifact_ids` so a workflow can be traced from planner/orchestrator behavior through generated artifacts and evaluation checks.

## Run With Docker Compose

```bash
docker compose up --build
```

Services:

- API: `http://localhost:8000`
- Postgres: `localhost:5432`
- Redis: `localhost:6379`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

Docker Compose configures the API and workflow worker with `AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy`,
`AEAI_RUN_REPOSITORY_CREATE_SCHEMA=true`, and
`AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os`, so API-created
runs survive API and worker restarts while the `postgres_data` volume exists. Use
`docker compose down -v` only when you intentionally want to delete that local run state.

Stop services:

```bash
docker compose down --remove-orphans
```

## Scaffold Layout

```text
src/aeai_os/
  api/              FastAPI app factory and health endpoint
  agents/           Agent interfaces and registry
  analytics/        Procurement KPIs and safe-code policy
  artifacts/        Artifact lineage helpers
  data/             CSV profiling and query adapters
  evaluation/       Deterministic quality gates and rubrics
  orchestration/    Execution graph primitives
  reports/          Markdown report rendering helpers
  schemas/          Shared enums and lightweight DTOs
  security/         Tool permission and approval policy
  storage/          Artifact storage backends and path helpers
  visualization/    Static dashboard and chart rendering helpers
tests/              Unit tests for scaffold contracts
scripts/            Local maintenance and smoke scripts
docs/               Architecture and developer docs
```

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
- Prometheus: [http://127.0.0.1:9090](http://127.0.0.1:9090)
- Grafana: [http://127.0.0.1:3000](http://127.0.0.1:3000)

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
and `/admin` endpoints require either `Authorization: Bearer <token>` or
`X-AEAI-API-Key: <token>`.
Configure accepted credentials with `AEAI_AUTH_TOKEN_PROFILES` as semicolon-separated
`token=user_id|display_name|roles` entries, for example
`operator-token=operator-1|Operator One|operator;reviewer-token=reviewer-1|Reviewer One|reviewer`.
Supported roles are `viewer` for read-only inspection, `operator` for run and artifact mutations,
`reviewer` for approval decisions, and `admin` for all current capabilities. The legacy `approver`
role is also accepted for compatibility. Mutating API actions write structured `audit` events with
actor identity, action, target, run ID, trace ID, and timestamp. Audit history is included in run
detail responses and is also available at `/runs/{run_id}/audit-events`.

| Route | Purpose |
| --- | --- |
| `POST /runs` | Create an agent workflow run |
| `POST /runs/import` | Import a portable run archive for offline inspection |
| `GET /runs/{run_id}` | Inspect run state, artifacts, evaluations, and trace ID |
| `GET /runs/{run_id}/export` | Export run metadata, artifacts, graph nodes, events, jobs, evaluations, and checkpoint |
| `GET /runs/{run_id}/audit-events` | Inspect structured audit history for protected actions |
| `POST /runs/{run_id}/datasets/reference` | Attach an external dataset reference |
| `POST /runs/{run_id}/datasets/upload` | Upload a local dataset file |
| `POST /runs/{run_id}/execute/procurement` | Execute synchronously in local mode or enqueue when `AEAI_WORKFLOW_EXECUTION_MODE=async` |
| `POST /runs/{run_id}/execute/procurement/async` | Queue the procurement workflow explicitly |
| `GET /runs/{run_id}/workflow-jobs` | Inspect queued workflow jobs |
| `POST /runs/{run_id}/workflow-jobs/{job_id}/retry` | Requeue a dead-lettered workflow job for manual recovery |
| `POST /runs/{run_id}/workflow-jobs/{job_id}/dismiss` | Mark a dead-lettered workflow job as dismissed |
| `POST /runs/{run_id}/deployments` | Request approval to promote artifacts |
| `POST /runs/{run_id}/deployments/{job_id}/approval` | Approve or deny a deployment request |
| `GET /runs/{run_id}/graph-nodes` | Inspect execution graph node state |
| `GET /runs/{run_id}/events` | Inspect agent event telemetry |
| `GET /runs/{run_id}/timeline` | Inspect chronological run activity |
| `POST /runs/{run_id}/graph-nodes/{node_id}/approval` | Approve or deny a waiting graph node |
| `POST /runs/{run_id}/graph-nodes/{node_id}/retry` | Retry a failed graph node |
| `GET /runs/{run_id}/evaluations` | List evaluation results for a run |
| `GET /app` | Browser control plane for creating and browsing runs |
| `GET /app/artifacts` | Browser artifact browser with dashboard/report previews |
| `GET /app/admin` | Browser admin UI for agent, connector, credential, and policy inspection |
| `GET /run-inspector/runs/{run_id}` | Browser run inspector UI |
| `GET /runs/{run_id}/artifacts/{artifact_id}/content` | Preview or download safe artifact payloads |
| `GET /admin/agents` | List registered agents, capabilities, and risk profiles |
| `GET /admin/policies` | List registered tool permissions and policy rules |
| `GET /admin/affected-runs` | List recent connector or policy affected runs with inspector links |
| `GET /connectors` | List registered enterprise connectors and current status |
| `GET /connectors/credential-profiles` | List sanitized credential profile references |
| `GET /connectors/{connector_id}/health` | Inspect connector configuration health |
| `POST /data-sources` | Register and validate a reusable enterprise dataset source |
| `GET /data-sources` | List registered dataset sources |
| `GET /data-sources/{data_source_id}` | Inspect a registered dataset source |
| `POST /data-sources/{data_source_id}/validate` | Re-check source reachability before execution |
| `GET /metrics` | Prometheus-compatible run and agent metrics |
| `GET /health` | Service health |
| `GET /docs` | Interactive OpenAPI documentation |

## Connector Registry

The platform exposes first-class connector metadata for warehouse, object storage, and source-control
integrations. Credential profiles are environment-backed references, not secret payloads. API
responses only show configured/missing environment keys and never return secret values.
For deployed environments, secret-bearing settings can be loaded from mounted files by setting
`<ENV_NAME>_FILE`; direct environment variables still take precedence for local development.
Supported secret-file settings include `AEAI_DATABASE_URL_FILE`,
`AEAI_AUTH_TOKEN_PROFILES_FILE`, `AEAI_ARTIFACT_S3_ACCESS_KEY_ID_FILE`,
`AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY_FILE`, `MINIO_ACCESS_KEY_FILE`,
`MINIO_SECRET_KEY_FILE`, and `SNOWFLAKE_PASSWORD_FILE`.

Default connector IDs:

- `local-file` for local CSV, TSV, JSON, and Parquet dataset files
- `sqlite-local` for local SQLite warehouse references
- `snowflake-default` for Snowflake warehouse access
- `artifact-store` for local or S3-compatible artifact storage
- `github-default` for GitHub metadata, issue, and PR integrations

Warehouse dataset metadata can include `credential_profile` or `credential_profile_id` to bind a
dataset reference to a profile such as `snowflake-default` without storing credentials in artifact
metadata.

Do not place raw passwords, tokens, API keys, private keys, connection strings, or presigned URLs in
data-source metadata, artifact metadata, workflow job payloads, or free-form event payloads. Public
API serializers and run archives redact common secret-like keys and URI credentials defensively, but
connectors should pass credential material through environment variables or mounted secret files.

## Data Source Onboarding

Register reusable dataset sources through `/data-sources` so users can start workflow runs without
hard-coding file paths or warehouse relation metadata into application code. A source stores its type,
connector ID, credential profile reference, dataset URI, owner, and non-secret metadata. The API
validates local files and SQLite references for reachability, and checks Snowflake profile
configuration before accepting Snowflake-backed sources.

Example local source:

```bash
curl -s -X POST http://127.0.0.1:8000/data-sources \
  -H 'content-type: application/json' \
  -d '{
    "id": "procurement-local",
    "name": "Procurement Local CSV",
    "source_type": "local_file",
    "dataset_uri": "examples/procurement_demo.csv",
    "owner": "finance-ops",
    "metadata": {"domain": "procurement"}
  }'
```

Create a run from the registered source:

```bash
curl -s -X POST http://127.0.0.1:8000/runs \
  -H 'content-type: application/json' \
  -d '{
    "task": "Analyze procurement spend and create a dashboard report.",
    "data_source_id": "procurement-local"
  }'
```

The run metadata and dataset artifact metadata both record `data_source_id`, `connector_id`, and
`credential_profile_id` for auditability.

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
Docker Compose sets `AEAI_WORKFLOW_EXECUTION_MODE=async`, so the primary execute endpoint returns a
queued job immediately and the worker completes it in the background.

Run the procurement workflow through the local API:

```bash
RUN_ID=$(curl -s -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task":"Analyze this procurement dataset and create a dashboard report.","dataset_uri":"examples/procurement_demo.csv"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -X POST "http://127.0.0.1:8000/runs/${RUN_ID}/execute/procurement"
curl "http://127.0.0.1:8000/runs/${RUN_ID}/workflow-jobs"
curl "http://127.0.0.1:8000/runs/${RUN_ID}"
```

Open `http://127.0.0.1:8000/app` to create a run from the browser, choose a registered data source
or dataset URI, browse recent runs, and open any run directly in Run Inspector.
Open `http://127.0.0.1:8000/app/artifacts` to browse generated artifacts by run and producer node,
preview HTML dashboards/charts and markdown reports, inspect lineage, and copy or download safe
artifact links.
Open `http://127.0.0.1:8000/app/admin` to inspect registered agents, connector health,
credential profiles, policy rules, and connector/policy affected runs from one operations view.

Open `http://127.0.0.1:8000/run-inspector/runs/${RUN_ID}` to inspect graph nodes,
events, artifact lineage, approval history, evaluation/MLflow status, deployment history, and
approve/deny or retry actionable nodes.

## Run Archives

Completed runs can be exported as portable JSON archives for portfolio demos, debugging, and
offline replay in Run Inspector. Archives include run metadata, artifacts, graph nodes, events,
workflow jobs, evaluations, and checkpoint state, but not artifact payload bytes. Secret-like keys
such as passwords, tokens, API keys, and credentials are redacted during export. The same redaction
is applied to public run, artifact, event, timeline, workflow-job, and data-source API responses so
Run Inspector can be used for demos without exposing connector credentials.

```bash
PYTHONPATH=src .venv/bin/python scripts/manage_run_archive.py \
  --database-url sqlite+pysqlite:///./runs.db export "$RUN_ID" --output run-archive.json

PYTHONPATH=src .venv/bin/python scripts/manage_run_archive.py \
  --database-url sqlite+pysqlite:///./offline-runs.db --create-schema replay \
  --input run-archive.json
```

The API offers the same flow with `GET /runs/{run_id}/export` and `POST /runs/import`. After replay,
open `/run-inspector/runs/{run_id}` against the local API to inspect the imported run without the
original infrastructure.

## Kubernetes Baseline

Validate the Kubernetes manifests locally:

```bash
make k8s-validate
```

The baseline in `deploy/kubernetes/` includes the API, workflow worker, Postgres, Redis, MinIO,
config, secrets, services, health probes, observability environment variables, and local/staging/
production-style overlays. See [deploy/kubernetes/README.md](deploy/kubernetes/README.md) for
kind/minikube deployment, staging apply, production configuration, and teardown steps.

With authentication enabled, include a configured bearer token:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer operator-token" \
  -d '{"task":"Analyze this procurement dataset and create a dashboard report."}'
```

`AEAI_WORKFLOW_EXECUTION_MODE=sync` keeps one-process local demos simple. Set
`AEAI_WORKFLOW_EXECUTION_MODE=async` for production-like API behavior where execution requests
enqueue workflow jobs and workers process them separately. Queued workflow execution defaults to the
repository-backed queue. Set `AEAI_WORKFLOW_QUEUE_BACKEND=redis` to use Redis as the pending-job
broker while keeping the run repository as the authoritative execution guard. Workers heartbeat
claimed jobs, recover timed-out claims, retry according to `max_attempts`, and move exhausted jobs to
`dead_letter`. Procurement job retries default to `AEAI_PROCUREMENT_WORKFLOW_MAX_ATTEMPTS=3`.
Dead-lettered jobs remain inspectable through `/runs/{run_id}/workflow-jobs` and the Run Inspector,
where operators can manually retry or dismiss them.

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
- AWS deployment path: [deploy/cloud/aws/README.md](deploy/cloud/aws/README.md)

## Tests

```bash
make lint
make test
make smoke
make demo
make k8s-validate
make cloud-validate
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

Local OTLP/HTTP collector smoke setup:

```bash
docker run --rm -p 4318:4318 -p 4317:4317 \
  -v "$PWD/deploy/otel-collector-config.yaml:/etc/otelcol-contrib/config.yaml:ro" \
  otel/opentelemetry-collector-contrib:latest \
  --config=/etc/otelcol-contrib/config.yaml

AEAI_TRACE_EXPORTER=otlp_http \
AEAI_OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces \
PYTHONPATH=src .venv/bin/python -m uvicorn aeai_os.api.app:create_app \
  --factory --host 127.0.0.1 --port 8000
```

Major spans include API requests, workflow enqueue/process steps, procurement execution, planner
graph creation, agent nodes, policy decisions, warehouse queries, data-source validation, artifact
reads/writes, and evaluation logging. Correlation attributes include `run.id`, `run.trace_id`,
`workflow.name`, `workflow.job.id`, `graph.node.id`, `agent.type`, `connector.id`,
`credential_profile.id`, and artifact storage metadata. API responses expose `x-trace-id`; run
records keep a durable `trace_id`, and emitted run events store that durable ID plus the active
request/worker `otel_trace_id`.

MLflow tracking is disabled by default. Set `AEAI_MLFLOW_TRACKING_ENABLED=true` and
`AEAI_MLFLOW_TRACKING_URI` to mirror evaluation scores, pass/fail state, check metrics, run IDs, and
trace IDs into an MLflow experiment.

LangSmith trace review is disabled by default. Set `AEAI_LANGSMITH_TRACING_ENABLED=true`,
`AEAI_LANGSMITH_API_KEY`, and optionally `AEAI_LANGSMITH_PROJECT` to mirror agent events and
evaluation results into LangSmith with run IDs, trace IDs, graph node IDs, agent names, and artifact
IDs in metadata.

### Operational Dashboards

Prometheus and Grafana are packaged for local demos through Docker Compose:

```bash
docker compose up api workflow-worker prometheus grafana
```

Prometheus loads `deploy/prometheus/prometheus.yml` and scrapes `/metrics` from the API service. The
API metrics include workflow job status, attempts, and duration, so worker progress is visible even
though workers do not expose a separate HTTP server. Grafana provisions Prometheus as the default
data source and loads `deploy/grafana/provisioning/dashboards/aeai-operational-dashboard.json`.

Open Grafana at [http://127.0.0.1:3000](http://127.0.0.1:3000) with `admin` /
`aeai_grafana`, then open **Autonomous Enterprise AI OS Operations**. During demos, inspect:

- **Run Status** for pending/running/completed/failed workflow state
- **Run Latency** for average and p95 lifecycle duration
- **Workflow Jobs** and **Workflow Job Latency** for queued/running/dead-letter worker activity
- **Evaluation Score** and pass/fail counts for output quality
- **Agent Node State** for planner/data/analytics/visualization/report/evaluation progress
- **Artifacts by Type** for dataset, KPI, chart, dashboard, report, code, and deployment outputs

## Governance Policy Engine

Workflow graph execution evaluates each node's required tools before an agent runs. The default
policy registry classifies tools by permission level, risk, and explicit governance rules:

- Read-only dataset/profile/evaluation tools are allowed.
- Deployment promotion requires approval.
- External connector access, such as Snowflake or external HTTP, is escalated to
  `platform-security`.
- Sensitive artifacts marked with metadata such as `sensitive`, `pii`, `contains_pii`, or `secret`
  require approval before reader tools execute.
- Destructive tools such as `delete_artifact` and `shell_exec` are denied.

Policy decisions are recorded as `tool_call` events with `policy_rule_id`, decision, reason,
escalation target, approval state, and policy context. Run Inspector shows these decisions in
**Decision History** next to approval requests and deployment approvals.

Custom rules can be registered programmatically:

```python
from aeai_os.security import PolicyRule, ToolPolicyDecisionStatus, build_policy_registry_from_rules

policy_registry = build_policy_registry_from_rules(
    [
        PolicyRule(
            id="retry-warehouse-maintenance",
            description="Retry Snowflake work during maintenance.",
            decision=ToolPolicyDecisionStatus.RETRY,
            reason="Warehouse maintenance window is active.",
            tool_patterns=["snowflake_query"],
            retry_after_seconds=60,
        )
    ]
)
```

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

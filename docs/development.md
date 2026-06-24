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
make smoke
make test
make lint
make demo
```

`make smoke` only uses the Python standard library and verifies the scaffold shape plus the health payload.
`make demo` runs the end-to-end procurement agent workflow and writes generated artifacts under
`artifacts/procurement_demo/<run_id>/`.

## Run The API Locally

```bash
make dev
```

Then open:

- API health: `http://localhost:8000/health`
- API metrics: `http://localhost:8000/metrics`
- API docs: `http://localhost:8000/docs`

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
```

Execute the procurement workflow for a run with an attached dataset:

```bash
curl -X POST http://localhost:8000/runs/{run_id}/execute/procurement
```

The execution response includes run status, trace ID, completed/failed node IDs,
waiting-for-approval state, artifacts, and evaluations.

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

## Orchestrator Kernel

The SCRUM-9 orchestration kernel runs validated execution graphs against registered agents and stores each state transition in the run repository.

Current local behavior:

- Multi-step graphs execute in dependency order.
- Run checkpoints persist the LangGraph-compatible state shape.
- Failed nodes retry according to `RetryPolicy` without restarting completed nodes.
- Nodes that return `waiting_for_approval` pause the run until `approve_node` resumes it.
- `POST /runs/{run_id}/execute/procurement/async` persists a workflow job for background
  processing.
- `scripts/run_workflow_worker.py` claims one queued procurement job, executes the workflow, and
  records completion, retry, or failure state.

The in-memory repository remains the default local checkpoint backend. Set
`AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy` and `AEAI_DATABASE_URL` to use the durable SQLAlchemy
repository against Postgres or SQLite-compatible test databases. The SQLAlchemy backend persists
runs, workflow jobs, graph nodes, artifacts, agent events, evaluations, and checkpoints behind the
same repository contract.

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
- `SnowflakeQueryAdapter` defines the future warehouse adapter boundary without requiring Snowflake credentials in the MVP.

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
- `GET /metrics` exposes run counts, run status totals, error totals, artifact count, evaluation count and average score, node retry totals, run duration totals, and node status counts by agent.

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

The API uses the in-memory run repository unless configured otherwise. To persist run state in the
Compose Postgres service, set `AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy` and
`AEAI_DATABASE_URL=postgresql+psycopg://aeai:aeai_password@postgres:5432/aeai_os` in the service
environment before starting the API.

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
  storage/          Artifact path helpers
  visualization/    Static dashboard and chart rendering helpers
tests/              Unit tests for scaffold contracts
scripts/            Local maintenance and smoke scripts
docs/               Architecture and developer docs
```

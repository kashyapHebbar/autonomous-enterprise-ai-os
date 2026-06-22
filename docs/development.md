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
```

`make smoke` only uses the Python standard library and verifies the scaffold shape plus the health payload.

## Run The API Locally

```bash
make dev
```

Then open:

- API health: `http://localhost:8000/health`
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

## Orchestrator Kernel

The SCRUM-9 orchestration kernel runs validated execution graphs against registered agents and stores each state transition in the run repository.

Current local behavior:

- Multi-step graphs execute in dependency order.
- Run checkpoints persist the LangGraph-compatible state shape.
- Failed nodes retry according to `RetryPolicy` without restarting completed nodes.
- Nodes that return `waiting_for_approval` pause the run until `approve_node` resumes it.

The in-memory repository is the MVP checkpoint backend. The same model is mirrored by SQLAlchemy table definitions so a Postgres-backed repository can replace it later.

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
  data/             CSV profiling and query adapters
  orchestration/    Execution graph primitives
  schemas/          Shared enums and lightweight DTOs
  storage/          Artifact path helpers
  evaluation/       Evaluation/rubric primitives
tests/              Unit tests for scaffold contracts
scripts/            Local maintenance and smoke scripts
docs/               Architecture and developer docs
```

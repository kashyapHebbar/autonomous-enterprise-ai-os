# Autonomous Enterprise AI Operating System

An MVP for a durable multi-agent workflow platform where specialized AI agents collaborate on enterprise analytics tasks.

The first vertical slice is a procurement analytics workflow:

1. A user submits a request and dataset.
2. A planner agent creates an execution graph.
3. Data, analytics, visualization, report, evaluation, and security agents execute the graph.
4. The platform stores run state, artifacts, evaluation results, and observability traces.
5. The user receives a dashboard/report with linked provenance.

## Project Status

Current Jira milestone: `SCRUM-9 - Build LangGraph orchestrator with durable execution`

The architecture blueprint is in [docs/architecture.md](docs/architecture.md).
Local development instructions are in [docs/development.md](docs/development.md).

## MVP Technology Direction

- Orchestration: LangGraph
- API: FastAPI
- State store: Postgres
- Cache/queue/checkpoint support: Redis
- Artifacts: local object-store compatible layout for MVP, S3/MinIO-ready later
- Observability: OpenTelemetry, Prometheus-compatible metrics, MLflow or LangSmith
- Packaging: Docker Compose first, Kubernetes later

## Quick Start

```bash
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

Core API endpoints:

- `POST /runs` creates a run from a natural-language task.
- `GET /runs/{run_id}` returns run status and artifacts.
- `POST /runs/{run_id}/datasets/reference` attaches an external dataset URI.
- `POST /runs/{run_id}/datasets/upload` uploads a local dataset file.
- `GET /runs/{run_id}/artifacts` lists artifacts for a run.

Core orchestration capabilities:

- `LangGraphRunState` captures task, plan, outputs, artifacts, approvals, evaluations, and errors.
- `OrchestratorService` executes dependency-ordered agent graphs with repository checkpoints.
- Failed nodes retry without resetting completed graph work.
- Approval-required nodes pause the run and resume after an explicit decision.

Run the full local stack:

```bash
docker compose up --build
```

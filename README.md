# Autonomous Enterprise AI Operating System

An MVP for a durable multi-agent workflow platform where specialized AI agents collaborate on enterprise analytics tasks.

The first vertical slice is a procurement analytics workflow:

1. A user submits a request and dataset.
2. A planner agent creates an execution graph.
3. Data, analytics, visualization, report, evaluation, and security agents execute the graph.
4. The platform stores run state, artifacts, evaluation results, and observability traces.
5. The user receives a dashboard/report with linked provenance.

## Project Status

Initial Jira milestone: `SCRUM-6 - Define platform architecture and MVP scope`

The architecture blueprint is in [docs/architecture.md](docs/architecture.md).

## MVP Technology Direction

- Orchestration: LangGraph
- API: FastAPI
- State store: Postgres
- Cache/queue/checkpoint support: Redis
- Artifacts: local object-store compatible layout for MVP, S3/MinIO-ready later
- Observability: OpenTelemetry, Prometheus-compatible metrics, MLflow or LangSmith
- Packaging: Docker Compose first, Kubernetes later

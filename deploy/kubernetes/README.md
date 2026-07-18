# Kubernetes Baseline

These manifests provide a local-cluster baseline for the Autonomous Enterprise AI OS API, workflow
worker, and development dependencies.

Included resources:

- Namespace: `aeai-os`
- API deployment and ClusterIP service
- Workflow worker deployment
- Shared config map and secret template
- Postgres, Redis, and MinIO deployments and services for local clusters
- Startup, readiness, and liveness probes where applicable
- Observability environment variables with optional OTLP settings

## Validate Locally

Run the manifest validator before applying:

```bash
make k8s-validate
```

If `kubectl` is installed, you can also ask Kubernetes to dry-run the kustomization:

```bash
kubectl apply --dry-run=client -k deploy/kubernetes
```

## Run With kind

Create a local cluster:

```bash
kind create cluster --name aeai-os
```

Build and load the image:

```bash
docker build -t ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:latest .
kind load docker-image ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:latest \
  --name aeai-os
```

Apply the baseline:

```bash
kubectl apply -k deploy/kubernetes
kubectl -n aeai-os rollout status deployment/postgres
kubectl -n aeai-os rollout status deployment/redis
kubectl -n aeai-os rollout status deployment/minio
kubectl -n aeai-os rollout status deployment/aeai-api
kubectl -n aeai-os rollout status deployment/aeai-worker
```

Open the API:

```bash
kubectl -n aeai-os port-forward service/aeai-api 8000:8000
```

Then visit:

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- Metrics: http://127.0.0.1:8000/metrics

Open MinIO console when needed:

```bash
kubectl -n aeai-os port-forward service/minio 9001:9001
```

The default local credentials are in `api-secrets.yaml`.

## Run With minikube

Point Docker at minikube and build the image:

```bash
minikube start
eval "$(minikube docker-env)"
docker build -t ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:latest .
kubectl apply -k deploy/kubernetes
```

Expose the API:

```bash
kubectl -n aeai-os port-forward service/aeai-api 8000:8000
```

## Prometheus and Grafana

The local Docker Compose stack includes Prometheus and Grafana for demo dashboards. For Kubernetes,
reuse `deploy/prometheus/prometheus.yml` as the scrape baseline and point the API scrape target at
`aeai-api.aeai-os.svc.cluster.local:8000`. The exported API metrics include workflow job status,
attempts, and duration, so worker progress appears in Prometheus without a separate worker scrape
endpoint. Import or provision
`deploy/grafana/provisioning/dashboards/aeai-operational-dashboard.json` to inspect run throughput,
failures, latency, evaluation quality, agent state, workflow jobs, and artifact counts.

## Configuration Notes

For production-like environments, replace the local development secret values before applying:

- `AEAI_DATABASE_URL`
- `POSTGRES_PASSWORD`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`

The API also supports mounted secret files by setting variables such as
`AEAI_DATABASE_URL_FILE`, `AEAI_AUTH_TOKEN_PROFILES_FILE`,
`AEAI_ARTIFACT_S3_ACCESS_KEY_ID_FILE`, `AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY_FILE`,
`MINIO_ACCESS_KEY_FILE`, `MINIO_SECRET_KEY_FILE`, or `SNOWFLAKE_PASSWORD_FILE`. Use this when a
cluster mounts secrets as files instead of injecting their values directly into the container
environment.

To send traces to an OTLP collector, set these config map values:

- `AEAI_TRACE_EXPORTER=otlp_http` or `AEAI_TRACE_EXPORTER=otlp_grpc`
- `AEAI_OTEL_EXPORTER_OTLP_ENDPOINT`
- `AEAI_OTEL_EXPORTER_OTLP_HEADERS`
- `AEAI_OTEL_EXPORTER_OTLP_INSECURE`

For local collector testing, start a collector with `deploy/otel-collector-config.yaml` and point
`AEAI_OTEL_EXPORTER_OTLP_ENDPOINT` at its HTTP endpoint, for example
`http://otel-collector:4318/v1/traces` inside a cluster or `http://127.0.0.1:4318/v1/traces` from a
local API process.

The baseline sets `AEAI_WORKFLOW_EXECUTION_MODE=async` and `AEAI_WORKFLOW_QUEUE_BACKEND=redis`.
Execution requests enqueue workflow jobs through the API, and the `aeai-worker` deployment claims
and completes them outside the request lifecycle.

The included Postgres, Redis, and MinIO deployments use `emptyDir` volumes and are intended for local
development only. Use managed services or persistent storage classes for production.

## Teardown

```bash
kubectl delete -k deploy/kubernetes
kind delete cluster --name aeai-os
```

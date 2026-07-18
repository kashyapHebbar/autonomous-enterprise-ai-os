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
- API and worker runtime configuration validation init containers
- Local, staging, and production-style kustomize overlays
- Observability environment variables with optional OTLP settings

## Environments

| Overlay | Path | Purpose |
| --- | --- | --- |
| Base | `deploy/kubernetes` | Local-cluster baseline with API, worker, Postgres, Redis, and MinIO |
| Local | `deploy/kubernetes/overlays/local` | Explicit local demo settings with auth disabled and tracing exporter disabled |
| Staging | `deploy/kubernetes/overlays/staging` | Production-like API and worker replicas, auth enabled, Redis queue, MinIO artifacts, and OTLP traces |
| Production | `deploy/kubernetes/overlays/production` | Higher API/worker resources, auth enabled, external S3-style artifact config, OTLP gRPC traces, and schema creation disabled |

## Validate Locally

Run the manifest validator before applying:

```bash
make k8s-validate
```

This validates the base and all overlays. To validate one overlay:

```bash
python3.11 scripts/validate_kubernetes_manifests.py deploy/kubernetes/overlays/staging
```

If `kubectl` is installed, you can also ask Kubernetes to dry-run the kustomization:

```bash
kubectl apply --dry-run=client -k deploy/kubernetes/overlays/staging
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

Apply the local overlay:

```bash
kubectl apply -k deploy/kubernetes/overlays/local
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
kubectl apply -k deploy/kubernetes/overlays/local
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

## Staging Apply

For a staging-style deployment, build and push an image first:

```bash
docker build -t ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:staging .
docker push ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:staging
```

Apply the overlay, then replace the generated placeholder secret values with real credentials:

```bash
kubectl apply -k deploy/kubernetes/overlays/staging
kubectl -n aeai-os create secret generic aeai-secrets \
  --from-literal=AEAI_DATABASE_URL='postgresql+psycopg://aeai:<password>@postgres:5432/aeai_os' \
  --from-literal=AEAI_AUTH_TOKEN_PROFILES='admin-token=admin-1|Platform Admin|admin' \
  --from-literal=AEAI_ARTIFACT_S3_ACCESS_KEY_ID='<minio-access-key>' \
  --from-literal=AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY='<minio-secret-key>' \
  --from-literal=POSTGRES_PASSWORD='<password>' \
  --from-literal=MINIO_ACCESS_KEY='<minio-access-key>' \
  --from-literal=MINIO_SECRET_KEY='<minio-secret-key>' \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aeai-os rollout restart deployment/aeai-api deployment/aeai-worker deployment/postgres deployment/minio
kubectl -n aeai-os rollout status deployment/aeai-api
kubectl -n aeai-os rollout status deployment/aeai-worker
```

The API and worker run `scripts/validate_runtime_config.py` in an init container before startup.
If a required value is missing or a staging/production value still starts with `REPLACE_WITH`,
the pod fails before the application process starts and prints the missing key.

## Production Configuration

The production overlay is intentionally production-style rather than cloud-specific. Before applying
it to a real cluster:

- Replace the `aeai-secrets` values with values from your cloud secret manager or an external-secrets operator.
- Point `AEAI_DATABASE_URL` to managed Postgres or another production database endpoint.
- Point `AEAI_REDIS_URL` to managed Redis or a production Redis deployment.
- Set `AEAI_ARTIFACT_STORAGE_BACKEND=s3` and configure `AEAI_ARTIFACT_S3_BUCKET`,
  `AEAI_ARTIFACT_S3_REGION`, `AEAI_ARTIFACT_S3_ACCESS_KEY_ID`, and
  `AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY`.
- Set `AEAI_OTEL_EXPORTER_OTLP_ENDPOINT` to your collector or observability vendor endpoint.
- Run database migrations before rolling out because the production overlay sets
  `AEAI_RUN_REPOSITORY_CREATE_SCHEMA=false`.

## Required Values

| Area | ConfigMap keys | Secret keys |
| --- | --- | --- |
| API | `AEAI_ENV`, `AEAI_SERVICE_NAME`, `AEAI_API_PORT`, `AEAI_AUTH_ENABLED` | `AEAI_AUTH_TOKEN_PROFILES` when auth is enabled |
| Database | `AEAI_RUN_REPOSITORY_BACKEND`, `AEAI_RUN_REPOSITORY_CREATE_SCHEMA`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER` | `AEAI_DATABASE_URL`, `POSTGRES_PASSWORD` |
| Queue and worker | `AEAI_WORKFLOW_EXECUTION_MODE`, `AEAI_WORKFLOW_QUEUE_BACKEND`, `AEAI_WORKFLOW_QUEUE_TIMEOUT_SECONDS`, `AEAI_WORKFLOW_QUEUE_KEY_PREFIX`, `AEAI_REDIS_URL`, `REDIS_HOST`, `REDIS_PORT` | None by default |
| Artifact storage | `AEAI_ARTIFACT_ROOT`, `AEAI_ARTIFACT_STORAGE_BACKEND`, `AEAI_ARTIFACT_S3_BUCKET`, `AEAI_ARTIFACT_S3_PREFIX`, `AEAI_ARTIFACT_S3_ENDPOINT_URL`, `AEAI_ARTIFACT_S3_REGION`, `MINIO_ENDPOINT`, `MINIO_BUCKET` | `AEAI_ARTIFACT_S3_ACCESS_KEY_ID`, `AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` |
| Observability | `AEAI_TRACING_ENABLED`, `AEAI_TRACE_EXPORTER`, `AEAI_OTEL_EXPORTER_OTLP_ENDPOINT`, `AEAI_OTEL_EXPORTER_OTLP_HEADERS`, `AEAI_OTEL_EXPORTER_OTLP_INSECURE`, `AEAI_MLFLOW_*` | None by default |

## Configuration Notes

For production-like environments, replace the local development secret values before applying:

- `AEAI_DATABASE_URL`
- `AEAI_AUTH_TOKEN_PROFILES`
- `AEAI_ARTIFACT_S3_ACCESS_KEY_ID`
- `AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY`
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

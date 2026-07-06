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

## Configuration Notes

For production-like environments, replace the local development secret values before applying:

- `AEAI_DATABASE_URL`
- `POSTGRES_PASSWORD`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`

To send traces to an OTLP collector, set these config map values:

- `AEAI_TRACE_EXPORTER=otlp_http` or `AEAI_TRACE_EXPORTER=otlp_grpc`
- `AEAI_OTEL_EXPORTER_OTLP_ENDPOINT`
- `AEAI_OTEL_EXPORTER_OTLP_HEADERS`
- `AEAI_OTEL_EXPORTER_OTLP_INSECURE`

The included Postgres, Redis, and MinIO deployments use `emptyDir` volumes and are intended for local
development only. Use managed services or persistent storage classes for production.

## Teardown

```bash
kubectl delete -k deploy/kubernetes
kind delete cluster --name aeai-os
```

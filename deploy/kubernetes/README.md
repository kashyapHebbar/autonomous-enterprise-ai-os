# Kubernetes Baseline

These manifests are a follow-up-ready baseline for running the API in a Kubernetes cluster after
building and publishing an image.

They intentionally keep stateful dependencies external or separately managed. For local MVP work,
use Docker Compose first:

```bash
docker compose up --build
```

For Kubernetes:

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/api-configmap.yaml
kubectl apply -f deploy/kubernetes/api-deployment.yaml
kubectl apply -f deploy/kubernetes/api-service.yaml
```

Before applying to a real cluster, replace the image in `api-deployment.yaml` and point the
database, Redis, and object-store environment variables at managed services or in-cluster charts.

# AWS Deployment Path

This is the first opinionated cloud path for Autonomous Enterprise AI OS. It keeps local
development under Docker Compose and `deploy/kubernetes/overlays/local`, while AWS uses Terraform
for managed infrastructure and the production Kubernetes overlay for the app runtime.

## Target Architecture

| Platform area | AWS service | Purpose |
| --- | --- | --- |
| Compute | EKS with a managed node group | Runs the API and workflow worker Kubernetes deployments |
| Database | RDS for PostgreSQL | Durable run, artifact, workflow job, event, evaluation, and checkpoint metadata |
| Queue | ElastiCache Redis | Pending workflow job queue for async API/worker execution |
| Object storage | S3 | Generated dashboards, reports, charts, code, evaluations, and deployment artifacts |
| Secrets | Secrets Manager | Runtime values for database URL, admin token profile, Redis URL, and S3 credentials |
| Networking | VPC, public/private subnets, NAT gateway, security groups | Isolates data services and gives private workloads outbound access |
| Observability | OTLP endpoint configured through Kubernetes | Sends traces to a collector or vendor endpoint |

## Required Tools

- AWS CLI v2 authenticated to the target account
- Terraform 1.6+
- kubectl
- Docker with access to `ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os`

## Required AWS Permissions

Use an IAM role or user that can manage:

- EKS clusters, managed node groups, and EKS IAM roles
- EC2 VPCs, subnets, route tables, NAT gateways, security groups, and elastic IPs
- RDS PostgreSQL instances and subnet groups
- ElastiCache Redis replication groups and subnet groups
- S3 buckets, bucket versioning, and bucket encryption
- Secrets Manager secrets and secret versions
- IAM roles, policies, users, and access keys created by the Terraform stack

Terraform state contains generated credentials for RDS, the admin token profile, and the artifact
store access key. Store state in an encrypted backend before using this outside a sandbox account.

## Validate The Cloud Package

```bash
make cloud-validate
```

This checks that the AWS Terraform files, required resource types, outputs, and deployment docs are
present. It does not call AWS.

## Provision AWS Infrastructure

Copy and edit the example variables:

```bash
cd deploy/cloud/aws/terraform
cp terraform.tfvars.example terraform.tfvars
```

Set at least:

- `aws_region`
- `environment`
- `admin_cidr_blocks`
- node sizing values if you want different EKS capacity
- database and Redis sizing values if staging defaults are too small

Initialize and preview:

```bash
terraform init
terraform fmt -check
terraform validate
terraform plan -out=tfplan
```

Apply when the plan looks correct:

```bash
terraform apply tfplan
terraform output eks_update_kubeconfig_command
terraform output runtime_secret_name
terraform output artifact_bucket_name
```

Configure kubectl using the output:

```bash
aws eks update-kubeconfig --region <region> --name <cluster-name>
kubectl cluster-info
```

## Prepare Runtime Secrets

Terraform creates a Secrets Manager secret named like `aeai-os-staging/runtime`. The production
Kubernetes overlay still expects a Kubernetes secret called `aeai-secrets`, so sync the Secrets
Manager payload into the cluster before rollout:

```bash
aws secretsmanager get-secret-value \
  --secret-id "$(terraform output -raw runtime_secret_name)" \
  --query SecretString \
  --output text > /tmp/aeai-runtime.json

kubectl create namespace aeai-os --dry-run=client -o yaml | kubectl apply -f -
kubectl -n aeai-os create secret generic aeai-secrets \
  --from-literal=AEAI_DATABASE_URL="$(jq -r .AEAI_DATABASE_URL /tmp/aeai-runtime.json)" \
  --from-literal=AEAI_AUTH_TOKEN_PROFILES="$(jq -r .AEAI_AUTH_TOKEN_PROFILES /tmp/aeai-runtime.json)" \
  --from-literal=AEAI_ARTIFACT_S3_ACCESS_KEY_ID="$(jq -r .AEAI_ARTIFACT_S3_ACCESS_KEY_ID /tmp/aeai-runtime.json)" \
  --from-literal=AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY="$(jq -r .AEAI_ARTIFACT_S3_SECRET_ACCESS_KEY /tmp/aeai-runtime.json)" \
  --from-literal=POSTGRES_PASSWORD='managed-by-rds' \
  --from-literal=MINIO_ACCESS_KEY='unused-on-aws' \
  --from-literal=MINIO_SECRET_KEY='unused-on-aws' \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Deploy The App

Build and publish the production image tag used by `deploy/kubernetes/overlays/production`:

```bash
docker build -t ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:production .
docker push ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os:production
```

Run database migrations before the production overlay rolls out the API and worker:

```bash
export AEAI_DATABASE_URL="$(jq -r .AEAI_DATABASE_URL /tmp/aeai-runtime.json)"
PYTHONPATH=src python3.11 scripts/manage_database.py upgrade
PYTHONPATH=src python3.11 scripts/manage_database.py validate
```

Apply the Kubernetes production overlay:

```bash
kubectl apply -k deploy/kubernetes/overlays/production
kubectl -n aeai-os rollout status deployment/aeai-api
kubectl -n aeai-os rollout status deployment/aeai-worker
```

The API and worker init containers run `scripts/validate_runtime_config.py` first. If secrets or
required production config are missing, the pods fail before the application starts.

## Smoke Test The Deployment

Port-forward the API service:

```bash
kubectl -n aeai-os port-forward service/aeai-api 8000:8000
```

Verify the deployed API and UI:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/metrics
curl -I http://127.0.0.1:8000/app
curl -I http://127.0.0.1:8000/app/admin
curl -I http://127.0.0.1:8000/docs
```

With auth enabled, use the generated token from `AEAI_AUTH_TOKEN_PROFILES`:

```bash
TOKEN="$(jq -r .AEAI_AUTH_TOKEN_PROFILES /tmp/aeai-runtime.json | cut -d= -f1)"
curl -fsS http://127.0.0.1:8000/admin/agents \
  -H "Authorization: Bearer ${TOKEN}"
curl -fsS http://127.0.0.1:8000/connectors \
  -H "Authorization: Bearer ${TOKEN}"
```

Create one smoke run after the health checks pass:

```bash
curl -fsS -X POST http://127.0.0.1:8000/runs \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"task":"Cloud smoke test for the enterprise AI OS deployment."}'
```

Open:

- API UI: `http://127.0.0.1:8000/app`
- Admin UI: `http://127.0.0.1:8000/app/admin`
- API docs: `http://127.0.0.1:8000/docs`

## Teardown

Delete Kubernetes workloads first:

```bash
kubectl delete -k deploy/kubernetes/overlays/production
```

Then destroy cloud infrastructure:

```bash
cd deploy/cloud/aws/terraform
terraform destroy
```

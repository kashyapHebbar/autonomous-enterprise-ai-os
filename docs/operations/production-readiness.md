# Production Readiness

This document is the launch contract for the public Autonomous Enterprise AI OS service. A release
is eligible for production only when every automated gate passes and the staging evidence is linked
from the release record.

## Service Objectives

| Signal | Objective | Alert threshold | Owner |
| --- | --- | --- | --- |
| API availability | 99.9% over 30 days | Unavailable for 5 minutes | Platform on-call |
| Health endpoint latency | p95 below 500 ms | p95 above 500 ms for 15 minutes | Platform on-call |
| Workflow run latency | p95 below 120 seconds | p95 above 120 seconds for 15 minutes | AI platform on-call |
| Workflow success | At least 95% | Failed runs above 5% for 15 minutes | AI platform on-call |
| Recovery point objective (RPO) | 15 minutes for metadata; versioned artifacts | Backup or replication gap | Data platform on-call |
| Recovery time objective (RTO) | 60 minutes for regional service recovery | Recovery drill exceeds 60 minutes | Incident commander |

## Automated Gates

Run the static production package validation before every release:

```bash
make production-validate
```

Against the staging URL, run the security and bounded load gates:

```bash
python scripts/production_readiness.py security --url https://staging.example.com/health
python scripts/production_readiness.py load \
  --url https://staging.example.com/health \
  --requests 1000 --concurrency 25 --max-error-rate 0.01 --max-p95-ms 500 \
  --output artifacts/readiness/load.json
```

## Soak Test

Keep the release candidate in staging for at least 24 hours under representative scheduled traffic.
Record API availability, p95 latency, workflow success, queue depth, pod restarts, database CPU,
Redis memory, and WAF blocks. The soak passes when the objectives above hold, no critical alert is
unresolved, and no pod has repeated crash loops or memory kills.

## Failure Injection

Exercise one API pod termination while normal traffic continues:

```bash
python scripts/release_operations.py failure-drill \
  --base-url https://staging.example.com --recovery-seconds 120 \
  --confirm-production-impact
```

The drill passes when the endpoint remains available or recovers within 120 seconds, the replacement
pod becomes ready, and no accepted workflow is lost. Run database and Redis failover drills through
the cloud provider in a dedicated staging maintenance window.

## Launch

Provide the environment-specific values, render the manifest, review it, then deploy:

```bash
export AEAI_PUBLIC_HOSTNAME=api.example.com
export AEAI_ACM_CERTIFICATE_ARN=arn:aws:acm:region:account:certificate/id
export AEAI_WAF_ACL_ARN="$(terraform -chdir=deploy/cloud/aws/terraform output -raw waf_web_acl_arn)"
export AEAI_ARTIFACT_BUCKET="$(terraform -chdir=deploy/cloud/aws/terraform output -raw artifact_bucket_name)"
export AEAI_AWS_REGION=us-east-1
export AEAI_RUNTIME_SECRET_NAME="$(terraform -chdir=deploy/cloud/aws/terraform output -raw runtime_secret_name)"
export AEAI_IMAGE_REFERENCE=ghcr.io/kashyaphebbar/autonomous-enterprise-ai-os@sha256:<digest>
export AEAI_OIDC_ISSUER=https://identity.example.com
export AEAI_OIDC_AUDIENCE=aeai-os
export AEAI_OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
export AEAI_OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.example.com:4317
python scripts/release_operations.py render > /tmp/aeai-production.yaml
python scripts/release_operations.py deploy
```

Confirm health, metrics, authentication, a real connector probe, and one end-to-end workflow before
opening user traffic. Record the image digest, migration revision, WAF ARN, validation artifacts,
approver, and timestamp in the release record.

## Rollback

Rollback is the default response to a release-caused critical alert:

```bash
python scripts/release_operations.py rollback
```

After Rollback, verify both deployments, health, queue processing, and the last known-good workflow.
Database migrations must be backward compatible; destructive schema removal requires a later release.

## Launch Decision

The production reviewer must confirm: CI and security scans are green; the 24-hour Soak evidence is
attached; load and Failure injection gates pass; backup restore and regional RTO/RPO drills are
current; every critical alert has an owner and runbook; and launch and rollback commands were tested
against staging using the exact candidate image.

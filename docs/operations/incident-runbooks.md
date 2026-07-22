# Incident Runbooks

## API Unavailable

Owner: Platform on-call. Check the ALB target health, WAF blocks, API deployment readiness, recent
rollout events, database reachability, and Redis reachability. Roll back a recent release when the
failure began after deployment. Escalate to the incident commander after 10 minutes or when more than
one region or data service is affected.

## Run Failures

Owner: AI platform on-call. Group failed runs by error summary, connector, agent node, and release.
Disable a failing connector or workflow version, preserve trace IDs, and replay only idempotent jobs.
Escalate security-policy failures to the security owner and data-quality failures to the source owner.

## Dead Letter Jobs

Owner: Workflow on-call. Inspect the job attempt history and its run trace before retrying. Correct
the dependency or configuration first, then requeue a bounded set. Never bulk replay deployment or
external-write jobs without approval.

## Run Latency

Owner: AI platform on-call. Inspect queue age, worker saturation, connector latency, database locks,
and agent-node histograms. Scale workers only when the dependency is healthy. Rate-limit new work if
queue age continues to grow, and preserve capacity for active enterprise workflows.

## Backup Or Restore Failure

Owner: Data platform on-call. Stop the affected backup schedule, retain all prior recovery points,
capture tool output without credentials, and run the restore against an isolated drill database.
Escalate immediately if the latest verified recovery point exceeds the 15-minute RPO.

## Security Event

Owner: Security on-call. Preserve WAF samples and audit logs, rotate affected credentials, disable the
smallest compromised identity or connector, and block confirmed abusive indicators. Do not expose
request payloads or secrets in the incident channel. Follow the penetration-test checklist for
revalidation before restoring access.

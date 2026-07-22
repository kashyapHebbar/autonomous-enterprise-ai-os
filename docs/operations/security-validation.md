# Security Validation

Automated pull-request checks run CodeQL, dependency review, filesystem and IaC scanning, and a built
container scan. A critical or high finding blocks release unless the security owner documents a
time-bounded exception.

## Penetration-Test Checklist

- Verify OIDC issuer, audience, signature, expiry, organization, workspace, and role enforcement.
- Attempt cross-tenant reads and writes for runs, artifacts, connectors, sources, and investigations.
- Test path traversal, SQL identifier injection, object-prefix escape, SSRF, and oversized uploads.
- Confirm raw credentials never appear in API responses, traces, metrics, archives, or UI storage.
- Exercise WAF managed rules and per-IP rate limiting without using production customer traffic.
- Verify HTTPS-only access, TLS policy, HSTS, CSP, frame denial, MIME sniffing denial, and referrer policy.
- Test privilege escalation across viewer, operator, admin, connector, and deployment actions.
- Verify destructive, external-network, code-execution, and deployment tools require policy approval.
- Scan the final image digest and software bill of materials; reconcile all high findings.
- Confirm backup files, Terraform state, Kubernetes secrets, and readiness artifacts have restricted access.

Run an independent penetration test before the first public launch and after material identity,
connector, execution-sandbox, or network-boundary changes.

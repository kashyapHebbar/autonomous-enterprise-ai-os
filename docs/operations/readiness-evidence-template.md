# Production Readiness Evidence

Use one copy of this record for each release candidate. Do not mark a gate passed without linking
the machine-generated output or provider event that proves it.

## Candidate

- Release version:
- Git commit:
- Immutable image digest:
- Staging hostname:
- Test window:
- Reviewer:

## Automated Evidence

| Gate | Result | Evidence link | Timestamp | Owner |
| --- | --- | --- | --- | --- |
| CI and unit/integration tests | Pending | | | Engineering |
| CodeQL, dependencies, filesystem/IaC, container scan | Pending | | | Security |
| Production manifest render and validation | Pending | | | Platform |
| Security header and HTTPS validation | Pending | | | Security |
| Load error rate and p95 threshold | Pending | | | Platform |
| 24-hour staging soak | Pending | | | Platform |
| API pod failure injection | Pending | | | Platform |
| PostgreSQL backup and isolated restore | Pending | | | Data platform |
| Regional recovery RPO/RTO | Pending | | | Incident commander |
| Launch and rollback rehearsal | Pending | | | Release manager |

## Review

- Open critical alerts:
- Accepted security exceptions and expiry:
- Known capacity constraints:
- Rollback image and migration revision:
- Go/no-go decision:
- Approvers and timestamps:

# Roadmap 13–16 implementation and validation

The canonical numbering is 13: large data; 14: connectors and ingestion;
15: identity/governance; 16: deployment/operations. Older filenames mentioning
Upgrade 14 scalable analytics and risk screening refer to roadmap item 13.

## 13 — Large data

Streaming summaries and disk-backed risk screening have backend coverage for
reconciliation, deterministic findings, cancellation, checkpoint/resume, source
mutation detection, workspace authorization, and the complete API-to-worker path.
The original six-agent workflow and Hugging Face integration remain available;
risk screening itself does not call a model.

## 14 — Enterprise ingestion

`aeai_os.connectors.ingestion` adds SQL (SQLAlchemy), Snowflake, S3 CSV, and HTTPS
REST ingestion. Each source belongs to an organization/workspace. SQLite commits
record upserts, hashes, audit history, and cursor in one transaction; a failed
page rolls back. Multiple workers serialize on the same database. An interrupted
export is recovered on the next tick. CSV exports use atomic replacement and
can be registered through the existing Data Sources UI/API for analysis.

Install the appropriate optional dependencies: `.[storage,warehouse]` for S3
and Snowflake. PostgreSQL's driver is already a core dependency. For other SQL
engines install their SQLAlchemy driver separately.

Start with `examples/ingestion/jobs.json`, then run:

```sh
PYTHONPATH=src .venv/bin/python scripts/run_ingestion_worker.py \
  --config examples/ingestion/jobs.json --loop
```

Set `AEAI_INGESTION_SQL_URL` (or its `_FILE` variant) to a read-only connection.
Configuration files are trusted operator-owned files; do not expose their creation
as an unrestricted user API. Use separate output paths per tenant/source, with
filesystem permissions that prevent cross-tenant access. No secrets belong in JSON.

Connector-specific configuration (in addition to common IDs and `primary_key`):

| kind | Fields | Change contract |
| --- | --- | --- |
| sql | connection_env, table, cursor_key | Unique, increasing key; 1,000 rows per tick |
| snowflake | connection_env, table, cursor_key | Same; env contains Snowflake connection JSON; identifiers must match returned case |
| s3 | bucket, key | IAM credentials; ETag-conditioned CSV download, maximum 50 MiB |
| rest | url, optional token_env | HTTPS JSON `{items: [...], next_cursor: ...}`; every nonempty page needs a new persistent cursor; 10 MiB/10,000 rows per page |

`interval_seconds` defaults to 300. Empty polls retain the cursor. Changing a source
configuration requires a new source ID to avoid applying an old cursor to new
semantics. SQL/Snowflake ingestion requires an append-only source or change-log
view with a unique monotonically increasing sequence. Updates to already-passed
keys and source deletions are not captured. S3 and REST upsert by primary key;
deletions are not propagated. This is incremental ingestion, not general CDC.
SQLite ingestion is a single-host control plane; do not put it on shared network
storage or run independent copies of its state database for the same source.

## 15 — Identity and governance

Existing token/OIDC authentication, roles, server-derived tenant/workspace scoping,
approval events, and administrative controls are covered by the identity/security
suite. Startup now rejects unknown authentication modes and rejects local auth,
missing token profiles/OIDC issuer/audience, or disabled security headers in
production/staging. `/ingestion/audit` is admin-only and filters by organization
and active workspace. It returns counts/source IDs, never credentials or data rows.

## 16 — Deployment and operations

Docker now builds the React frontend in a Node 22 stage and includes it in the
non-root Python image. Local Compose has separate API, workflow, monitoring and
risk workers; the malformed service nesting is repaired. Existing Kubernetes
overlays, AWS infrastructure, Redis workflow workers, metrics, tracing, recovery
utilities and deployment validation remain in place. Compose is a development
configuration with example credentials and source mounts; use the production
Kubernetes/cloud configuration for deployment. Ingestion scheduling is an opt-in
operator process with durable local storage, not a distributed Kubernetes worker.

## Validation boundary

Local backend, frontend build, lint, Kubernetes manifest, AWS package and production
readiness checks are run before commit. Connector protocol tests use mock S3,
Snowflake and REST services; SQL runs against a real temporary SQLite database.
No live Snowflake/S3/REST credentials, cloud infrastructure deployment, external
OIDC tenant, distributed ingestion, or production load/recovery exercise is
validated by these local tests. Production acceptance still requires those checks
against the intended environment. The local browser UI has build validation;
risk screening's end-to-end execution is tested at the HTTP API/worker boundary.

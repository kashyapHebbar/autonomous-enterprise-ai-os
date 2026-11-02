# Upgrade 11 — Persistent Workspace & Evidence-First Intelligence

## Scope delivered

- **Local persistence, opt-in**: Existing SQLAlchemy run repository now has an easy startup script using SQLite (`artifacts/aeai-local-runs.db`). Runs, checkpoints, agent events, model-budget events, evidence references, Q&A, and analyst calculation records persist across backend restarts. The existing local artifact storage keeps report files on disk.
- **Local CSV registry persistence**: An opt-in local catalog (`artifacts/aeai-local-sources.json`) saves registration names, paths and workspace/organization scope (not connector credentials or arbitrary metadata). It is written atomically with file mode `0600` and refuses symlinks; it does not persist Snowflake/SQLite connector credentials or registrations.
- **Homepage intelligence**: Read-only, workspace-scoped endpoint `GET /investigations/intelligence-overview` returns per-run verified KPI figures, observed trends, existing insights, recommendations and savings estimates from recorded artifacts. The React homepage presents selection, insight tabs, charts and drill-through links.
- **Reliability view**: `GET /investigations/workspace-health` reports persistent-vs-memory backend and stale/failed workflows. A stale run is **only flagged**, never automatically retried. Existing manual run/node retry endpoints remain unchanged.
- **Conversation context**: Follow-up questions use at most three prior run-scoped Q&A exchanges. Each new answer must still cite approved current evidence. An identical case-insensitive normalized saved question returns the original answer and evidence with **zero new Hugging Face calls**.
- **More analytical tools**: Governed cross-segment comparisons for supplier/category, category/month and department/month, with minimum two transactions per group, maximum 12 groups, and no arbitrary SQL or Python.
- **On-page chart drilldowns**: Search and sort saved chart groups without contacting the model or changing original verified totals.
- **Backups**: `scripts/backup_local_workspace.py` uses the SQLite online backup API, creates a private (`0600`) ZIP and optionally includes sensitive local artifacts (opt-in flag).

## Install and test (does not call Hugging Face)

```bash
cd ~/projects/autonomous-enterprise-ai-os
source .venv/bin/activate
python3 ~/Downloads/AEAI-Upgrade11-Apply.py --check
python3 ~/Downloads/AEAI-Upgrade11-Apply.py
AEAI_DYNAMIC_REASONING_ENABLED=false AEAI_REASONING_FOLLOWUPS_ENABLED=false python -m pytest -q tests/test_upgrade11_enterprise_intelligence.py
# On Apple Silicon M1, use native Homebrew Node first
# eval "$(/opt/homebrew/bin/brew shellenv)"
npm --prefix frontend run build
```

## Startup (important)

Stop an existing `make dev`, and from **the same backend terminal where `HF_TOKEN` is available**:

```bash
source .venv/bin/activate
bash scripts/start_persistent_local.sh
```

That script sets `AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy`, `AEAI_DATABASE_URL=sqlite:///artifacts/aeai-local-runs.db`, `AEAI_LOCAL_SOURCE_CATALOG_PATH=artifacts/aeai-local-sources.json`, and starts `make dev`. It does not change or reveal `HF_TOKEN`, alter the React `/app` router, or modify system-wide shell preferences.

**Existing in-memory workflows lost during earlier restarts cannot be recovered.** The new SQLite file will store future runs; it will not import old in-memory records. Existing manually registered sources must be re-registered once if they were not already in the optional local source catalog. Historical artifact files already on disk are not automatically linked to new run records.

## Verify after restart without spending credits

1. Create a workflow (model calls are optional and incur costs if enabled). To avoid HF charges for a smoke test set `AEAI_LLM_ENABLED=false` before starting the backend.
2. Check `/investigations/workspace-health` returns `persistent_runs: true`.
3. Stop and restart the backend with the same `bash scripts/start_persistent_local.sh` command. Confirm `/runs`, previously saved questions, and results remain available.
4. In the UI check **Home → What your investigations discovered**, and **AI Analyst** to review prior questions and calculations. Viewing or filtering these records never calls Hugging Face.

## Local backup

```bash
python scripts/backup_local_workspace.py
# Includes the database and source registrations only.
python scripts/backup_local_workspace.py --include-artifacts
# Includes reports and possibly confidential CSV uploads. Store privately.
```

An exported archive is **not** automatically restorable into a running database; stop the backend and follow a reviewed restoration procedure. For production-grade backups use tested database/volume snapshots and encryption. Never upload this archive to public repositories.

## Security and correctness

- The intelligence endpoints enforce the existing tenant/workspace access check. Numeric aggregates are scoped to their original completed run; **they are never added across unrelated analyses**.
- The model can only choose enumerated read-only tools. It does not execute arbitrary code, SQL, or shell commands.
- Question history is bounded and treated as untrusted data. Evidence identifiers remain backend-only; previously saved answer text is **not** treated as newly verified evidence.
- The `0.05 USD` workflow and `4.50 USD` monthly guards remain estimated application-side budgets, **not provider billing or guaranteed hard caps**. Refresh Hugging Face billing to see actual charges.
- The local source catalog and SQLite workspace are designed for a **single-user development machine**. They are not a substitute for enterprise secrets management, multi-user RBAC hardening, encrypted at-rest storage, production access controls, deployment, or scheduled workflow infrastructure.
- React's large-bundle warning is independent of backend data persistence and can be optimized in a later frontend performance pass.

## Compatibility

The installer never edits the locally customized `src/aeai_os/api/app.py` and preserves `frontend/src/main.tsx` routing with `<BrowserRouter basename="/app">`, the `/legacy-app` link, the repaired planner deduplication, existing agents/reports, and Hugging Face configuration. It creates a rollback snapshot and refuses unexpected file changes. Run the preflight first and do not use `--force`.

# Upgrade 10 — AI Analyst: calculate and chart new questions

Adds a separate **Ask AI to calculate something new** section on `/app/analyst` beside the existing Upgrade 9 explanation panel. Existing `/app` base path, `Original UI` link, original five/six agents, analytics, report formats and artifact IDs remain untouched.

## Safeguards

- Feature is **off by default** and requires an explicit click to run.
- Requires a **completed run**, authorized user, and local CSV referenced by that run.
- Dataset must live in project `examples/` or the configured managed `artifact_root/`, with a `.csv` extension, no symlink, at most 5 MB, at most 10,000 rows and 60 columns. The CSV must match the completed analytics' known measure/dimensions. This initial version does not support Snowflake, S3, parquet or arbitrary filesystem locations.
- Qwen can choose **one** from `supplier_totals`, `category_totals`, `department_totals`, `monthly_trend`, `supplier_monthly_trend`, and `period_comparison`, plus validated supplier and month filters. No arbitrary code, SQL, remote requests, write actions or query expressions.
- All figures are computed by deterministic Python aggregation. Groups with fewer than two records are suppressed; the UI explicitly says when results omit groups or only show the first twelve groups. Results are not a complete dataset export.
- Only short dimension option lists, the question and computed aggregate values go to Hugging Face. No raw CSV rows, source path, invoice IDs or user-specified arbitrary columns go to the model.
- Uses existing Hugging Face budget ledger and at most **two calls per question**: one to select the tool, another optional to explain grounded aggregate results. Set `AEAI_ANALYST_COMMENTARY_ENABLED=false` for **one call per question** (deterministic explanation).
- Record is stored as a `run_questions`-style event (`analyst_tool_record`) and can be retrieved later. With the default **in-memory backend**, it is lost when FastAPI restarts; see SQLite below.
- Quantities presented in charts/tables are from Python. AI narrative disallows unverified numeric claims and includes limitations.
- Per-run calculation limit defaults to 15; change with `AEAI_ANALYST_TOOLS_MAX_PER_RUN`.
- Estimated usage is app-side, **not** Hugging Face actual billing or a hard account cap.

## Enable

Backend terminal already exporting `HF_TOKEN`, `AEAI_LLM_ENABLED=true` and `AEAI_LLM_PROVIDER=huggingface`:

```bash
export AEAI_ANALYST_TOOLS_ENABLED=true
export AEAI_ANALYST_COMMENTARY_ENABLED=true
export AEAI_ANALYST_TOOLS_MAX_PER_RUN=15
make dev
```

You can start with commentary disabled to reduce calls:

```bash
export AEAI_ANALYST_COMMENTARY_ENABLED=false
```

No model requests occur during installation, running local tests, viewing the dashboard or listing previous answers.

## Optional: retain investigations across backend restarts

Your homepage showing **0 investigations** is expected if the backend was restarted with the default `memory` repository. The repository already supports SQLAlchemy and SQLite locally; no new database server is necessary. This is **opt-in** and won't recover runs previously lost from memory:

```bash
mkdir -p artifacts
export AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy
export AEAI_DATABASE_URL="sqlite:///artifacts/aeai-local-runs.db"
```

Set these **before** `make dev`, and keep a single worker for local development. Save `artifacts/` (database and generated files) when backing up. For production/multi-worker deployments, use PostgreSQL rather than SQLite.

## Build and verify

```bash
python -m pytest -q tests/test_upgrade10_analyst_tools.py
npm --prefix frontend run build
```

On Mac M1 if Node fails with `Bad CPU type in executable`:

```zsh
eval "$(/opt/homebrew/bin/brew shellenv)"
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
rehash
```

Select a **completed** workflow on `/app/analyst`. Ask `Compare supplier spending` and inspect the verified chart, exact amounts, and transaction counts.

## Known limitations

- An unrecognized dimension/supplier/month or aggregation that would expose a singleton group is rejected with a clear response. It is intentionally conservative.
- Full React build requires the project's npm dependencies; Python/mock API tests require no HF token.
- You can create saved calculated results via one or two Hugging Face requests per click. The original Upgrade 9 panel remains one request per click.

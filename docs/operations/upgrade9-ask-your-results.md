# Upgrade 9 — Ask About This Analysis

Upgrade 9 adds a **user-triggered, evidence-grounded Q&A** panel on completed workflow details. This is not a new six-agent run, a free-form autonomous shell/SQL agent, or an arbitrary RAG search over CSV rows.

## What changes

- The dashboard adds **Ask about this analysis** after a workflow completes, showing earlier questions, qualitative answers, and verified numbers beside the cited analytical checks.
- Read endpoint: `GET /runs/{run_id}/questions` (requires run-read permission).
- Write endpoint: `POST /runs/{run_id}/questions` with `{"question":"..."}` (requires run-write permission).
- Answers persist as normal run events in the configured repository; existing artifact IDs, calculations, reports and planning are unchanged.
- Only selected read-only aggregate checks already supported by `agents/investigation.py` are exposed to the model. Raw CSV rows, local paths and artifact URIs do not leave the server through this feature. The **user's question and a compact aggregate evidence summary are transmitted to Hugging Face**.
- Qwen's response cannot supply numerical claims directly; the UI displays exact verified numbers from Python next to each referenced evidence check. Citations identify computed artifact paths, not raw row-level provenance.

## Installation and verification

Stop FastAPI, then run the offline, backup-first installer from the project root:

```bash
python3 ~/Downloads/AEAI-Upgrade9-Apply.py
python -m pytest -q tests/test_upgrade9_run_questions.py tests/test_upgrade8_followup.py tests/test_upgrade7_dynamic_investigation.py tests/test_upgrade6_ai_budget.py tests/test_llm_upgrade.py
npm --prefix frontend run build
```

No Hugging Face token is used during installation or the mocked tests. No `app.py`, planner, existing report, or original raw data file is changed.

## Enabling it only when ready

In the **backend terminal** that has your Hugging Face token and settings:

```bash
export AEAI_RUN_QUESTIONS_ENABLED=true
export AEAI_RUN_QUESTIONS_MAX_PER_RUN=20
make dev
```

Each **click of Ask Qwen** makes at most **one** model request, budgeted by the existing monthly ledger and the configured per-workflow estimate. **The question allowance is per completed run, but each Q&A interaction has its own $0.05 estimated call budget; it is not a $0.05 total across the entire Q&A history.** You may lower `AEAI_LLM_WORKFLOW_BUDGET_USD` and `AEAI_LLM_MONTHLY_BUDGET_USD` for tighter estimated spending control. This is an application-side estimated guard, not an exact Hugging Face payment cap. Multiple app instances can have additional concurrency behavior; use centralized metering at scale.

Opening previous runs, expanding the panel, browsing previous answers, and using suggested questions (without clicking Ask) do **not** incur inference charges.

## Known limits

1. A question can only be answered from summary evidence already calculated in that workflow. The app does not interrogate raw invoices, execute arbitrary Python/SQL or fetch external systems.
2. The model can misunderstand even verified evidence. Its prose is qualitative, while all quantities displayed come from deterministic artifacts. This does **not** prove claims, misconduct or causality.
3. The feature is opt-in, with at most 20 successful saved questions per run by default; failed model calls can still incur provider charges.
4. Individual questions and responses are stored as run events, so run archives and authorized viewers may contain those interactions.
5. Q&A costs are included in the local usage ledger but are separate from a completed workflow's existing AI Usage panel. Estimated question costs appear beneath their answers.
6. Existing local in-memory repositories do not persist workflow history across backend restarts. Use the configured persistent repository for durable Q&A history.
7. A full production UI build and a real HF call should be verified on your machine. All package tests mock the model; no credits are required to install.

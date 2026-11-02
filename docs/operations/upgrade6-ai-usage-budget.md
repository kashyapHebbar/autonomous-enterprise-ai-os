# Upgrade 6 — Hugging Face AI usage and budget safeguards

This upgrade builds on **Upgrade 5 Hugging Face edition**. It does not change deterministic calculations or the user-modified planner validator. Every dynamic workflow shares a run-scoped usage tracker across its optional Qwen planner and AI briefing calls. The cost summary is persisted as an execution event and displayed in the Workflow Details page under **AI Usage & Budget**. Direct Python calls made via a gateway while `AEAI_LLM_ENABLED=true` are also accounted as separate direct sessions.

## Configure budgets (server-side environment variables)

```bash
export AEAI_LLM_ENABLED=true
export AEAI_LLM_PROVIDER=huggingface
export AEAI_LLM_MODEL=Qwen/Qwen3-32B
export AEAI_LLM_WORKFLOW_BUDGET_USD=0.05
export AEAI_LLM_MONTHLY_BUDGET_USD=4.50
export AEAI_LLM_MAX_CALLS_PER_RUN=3
export AEAI_LLM_MAX_OUTPUT_TOKENS=1800
export AEAI_HF_INPUT_USD_PER_MILLION=0.08
export AEAI_HF_OUTPUT_USD_PER_MILLION=0.25
# Your HF_TOKEN remains configured ONLY in the backend terminal; never commit it.
make dev
```

The $0.08/$0.25 rates are **example Qwen3-32B provider rates** from earlier analysis, **not automatically fetched Hugging Face billing rates**. If the HF router selects a different provider, adjust these variables to the applicable prices with a safety margin. Prices, credit balance, and reasoning token reporting can differ. A configurable $4.50 app-side monthly estimate allows headroom against the $5 prepaid deposit **but does not know how much was spent before this upgrade or outside this app**.

## What the guard guarantees and cannot guarantee

- The app will not initiate more than `AEAI_LLM_MAX_CALLS_PER_RUN` gateway requests in one tracked workflow.
- A prospective call is **blocked before HTTP** if its *estimated reserved price* exceeds remaining workflow or app-side monthly budget.
- Reservations are written to `artifacts/llm_usage.jsonl` and serialized across Mac/Linux worker processes using POSIX file locks. No external services or dependencies required. Keep this ledger on a shared, writable POSIX filesystem if multiple workers share the same Hugging Face account. Remote hosts with different filesystems are **not coordinated**.
- If the provider returns `usage.prompt_tokens` and `usage.completion_tokens`, reported counts supersede estimates; if not, the ledger conservatively retains the full reservation as an estimated bound. Both are still **pricing estimates**, not a provider invoice.
- Failed calls may still be booked as estimates; safe over-accounting avoids silently allowing further potentially costly calls. Crashed workers retain outstanding reservations. The ledger's monthly total resets naturally by UTC billing-calendar-month tag, not by the account's actual billing cycle.
- This is **not a hard monetary payment cap**. Providers may count and bill tokens differently, actual rates may vary, output counting may exceed configured assumptions, and API calls outside this app can consume credits. Configure Hugging Face billing controls separately.
- Budget exhaustion does not fail deterministic analytics: planner and briefing use their existing fallback behavior. Review `llm_usage_summary` in the execution event for `model_calls_blocked` and budget reasons.

## Read usage from local terminal

```bash
python3 - <<'PY'
import json
from urllib.request import urlopen
base='http://127.0.0.1:8000'
runs=json.load(urlopen(base+'/runs'))
run=max(runs, key=lambda x:x['created_at'])
events=json.load(urlopen(base+f"/runs/{run['id']}/events"))
for ev in events:
    if 'llm_usage_summary' in ev.get('payload', {}):
        print(json.dumps(ev['payload']['llm_usage_summary'], indent=2))
PY
```

### Test without consuming paid inference

```bash
python -m pytest -q tests/test_upgrade6_ai_budget.py
python -m pytest -q tests/test_llm_upgrade.py
npm --prefix frontend run build
```

All Upgrade 6 tests mock hosted responses. Configuration, ledger entries and frontend displays never contain the HF token or full prompts.

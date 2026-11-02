# Upgrade 5 — Hugging Face-only governed LLM reasoning

The complete Upgrade 5 implementation uses Hugging Face Inference Providers
for **both** optional AI-assisted planning and AI Analyst Briefings. No
OpenAI endpoint, Python SDK, model or API key is used.

## What it changes

1. The planner sends only a capped business task, column names, inferred types,
   row count and missing-value ratios to Hugging Face. It requests strict JSON
   (`procurement` or `generic`, selected goals, short rationale). Only supported
   recipes can pass validation. The graph is still your existing five fixed,
   registered, permission-declared agents.
2. The planner event persists the selected recipe and goals. The Data Retrieval
   Agent reads them, preventing independent recipe selection.
3. After deterministic KPI calculation and executive report creation, the
   Report Agent optionally obtains a non-numeric, clearly labelled AI Analyst
   Briefing from a small subset of aggregated insights and warnings. It creates
   a separate, dark-mode HTML artifact. The Markdown report, premium HTML
   executive report, evaluated numbers and analytics code are unchanged.
4. HF disabled, missing token, unsupported model, HTTP error, rate limit,
   invalid JSON, invalid recipe and service timeout -> fallback to the existing
   deterministic planning and reporting. No raw dataset rows are sent.

This **does not** let models run arbitrary SQL, code, tools or shell commands.
This release is model-assisted, NOT yet free-form autonomous planning.

## HF account and key

Get a *fine-grained* token at https://huggingface.co/settings/tokens with
**Make calls to Inference Providers** permission. Hosted inference can incur
billing; check your account quotas and rates.

On macOS zsh, from your existing AI OS project root, in the **same terminal**
that starts the backend:

```zsh
source .venv/bin/activate
export AEAI_LLM_ENABLED=true
export AEAI_LLM_PROVIDER=huggingface
export AEAI_LLM_MODEL=Qwen/Qwen3-32B
read -s 'HF_TOKEN?Paste HF token (hidden): '
echo
export HF_TOKEN
make dev
```

The key stays backend-side and should never be put in `frontend/`, `.env` files
committed to Git, screenshots, logs or chat messages. For a service deployment,
prefer a real secret manager and `HF_TOKEN_FILE` if supported by your platform.

No frontend rebuild is necessary: this patch changes only the Python backend.

## Configuration

| Setting | Default | Explanation |
| --- | --- | --- |
| `AEAI_LLM_ENABLED` | `false` | Always opt-in |
| `AEAI_LLM_PROVIDER` | `huggingface` | No OpenAI support in this edition |
| `AEAI_LLM_MODEL` | `Qwen/Qwen3-32B` | Default for both tasks |
| `AEAI_HF_PLANNER_MODEL` | empty | Override model for recipe/goal selection |
| `AEAI_HF_BRIEFING_MODEL` | empty | Override model for narrative summary |
| `AEAI_LLM_TIMEOUT_SECONDS` | `45` | Capped at 90 in gateway |
| `HF_TOKEN` / `HF_TOKEN_FILE` | empty | Fine-grained HF token |
| `HUGGING_FACE_HUB_TOKEN` / `HF_API_TOKEN` | empty | Token fallbacks |

Model IDs must use `namespace/model`. Optional `:cheapest`, `:fastest` or
`:preferred` routing policies are permitted. Model availability varies by
provider, region and time. The default Qwen3-32B has a documented HF hosted
Inference Provider and supports structured output. The routing protocol is
JSON chat completions directly to `https://router.huggingface.co/v1/chat/completions`,
NOT an OpenAI API call.

Try `AEAI_HF_BRIEFING_MODEL=deepseek-ai/DeepSeek-V3.2` for a second HF model,
provided your HF provider account supports it. Different models can differ in
schema support, pricing and reliability. Invalid/unsupported calls fall back.

## Verify

```bash
python -m pytest -q tests/test_llm_upgrade.py
python -m pytest -q
```

Then create a **new** procurement run. In the Workflow Details Logs tab look for
`planner_source: llm` and `planner_model: Qwen/Qwen3-32B`. The Outputs group
should show `AI Analyst Briefing` in addition to executive HTML and Markdown
reports. The briefing will **not** be present if the model call failed or was
not enabled; the normal workflow should still complete.

## Data sharing, safety and known limitations

- Hugging Face (and the selected hosted provider) sees the task text, schema
  headings and selected summarized insights. These can still be confidential.
  Obtain appropriate permission before enabling external inference.
- No raw receipts, CSV transaction rows or full artifacts are transmitted.
- JSON schema constrains structure; the planner and briefing perform additional
  validation. AI briefings are *not* evidence or verified financial claims.
- Report text cannot include numbers; KPIs and forecasts must come from your
  deterministic analytics artifacts.
- The endpoint has bounded input/output and timeouts; missing/failed HF calls
  degrade gracefully. A missing AI briefing does not block an evaluated report.
- Your local in-memory run storage still loses history after a server restart.
- This runs hosted models, not local M1 model inference. Fully offline HF model
  execution would require a separate quantized inference runtime and more work.

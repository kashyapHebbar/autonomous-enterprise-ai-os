# Upgrade 7 — governed dynamic investigation (Hugging Face)

This upgrade adds an **opt-in sixth Investigation Agent** to the dynamic workflow, without changing the five existing agent implementations, verified calculations, or API authentication. It requires Upgrade 6 and the existing Hugging Face Upgrade 5. It does **not** download models, call Hugging Face during installation, or introduce dependencies.

## Enable (after installation)

In the terminal used to start `make dev`, supply your existing HF_TOKEN securely and export:

```bash
export AEAI_LLM_ENABLED=true
export AEAI_LLM_PROVIDER=huggingface
export AEAI_LLM_MODEL=Qwen/Qwen3-32B
export AEAI_DYNAMIC_REASONING_ENABLED=true
export AEAI_REASONING_REVIEW_ENABLED=false
export AEAI_LLM_MAX_CALLS_PER_RUN=3
make dev
```

For optional **second model-based evidence review**, set `AEAI_REASONING_REVIEW_ENABLED=true` and raise the model-call allowance to 4. This is not recommended while validating the basic pipeline because it adds an API call. When disabled (the default), the original five-agent plan runs unchanged; install/test do not consume inference credits.

## How it works

1. The existing Hugging Face Planner classifies the dataset and chooses a supported analysis recipe, not executable code.
2. `analytics_code` computes the KPI analysis deterministically as before.
3. The new registered `investigation` agent receives only aggregate KPI values and allowed tool names. One bounded Qwen request selects up to three checks from `dataset_overview`, `data_quality`, `supplier_concentration`, `anomaly_triage`, `monthly_trend`, `savings_review`, `generic_segments`, and `generic_outliers` (only those available for the dataset). Duplicate suggestions are normalized; unsupported suggestions are rejected.
4. Python executes those checks on the **existing calculated analytics JSON**. No external queries, arbitrary SQL, code execution, network URLs, file paths, writes to source systems, or unregistered tools can be specified by the model.
5. Results are saved as a lineage-linked `Investigation Evidence (JSON)` and `Governed AI Investigation` HTML report (dark theme with print-to-PDF from the existing UI). They appear in **Outputs → Executive reports**. Tool selections and fallbacks appear in Execution Activity and Logs.
6. The existing Report and Evaluation agents run normally. Final Markdown and premium HTML reports are unchanged, and evaluation still uses the deterministic Markdown report; evidence is included in lineage.

**Optional reviewer:** With `AEAI_REASONING_REVIEW_ENABLED=true`, an additional LLM call receives only the verified check results. Its summary must cite known evidence IDs and cannot contain numerical claims. The reviewer is not authoritative; malformed outputs fall back while the investigation still succeeds.

### Model-call budget

With the default review disabled, a successful fully-enabled workflow ordinarily uses **3 model requests**: planner, investigation director, and report briefing. The Upgrade 6 guard limits calls, reserves estimated costs, enforces a local monthly application budget, and logs usage. These costs are estimates, not the provider's actual bill, and do not control calls made outside this application.

### Verifying after a future run

- **Execution:** look for the sixth `AI investigation` node.
- **Outputs:** `Governed AI Investigation` (HTML) and `Investigation Evidence (JSON)`.
- **Logs / Execution Activity:** `investigation_source: llm`, `selected_checks`, `evidence_artifact_id`, `review_status`.
- **AI Usage & Budget:** counts for `planner`, `investigation`, and `briefing`.
- No inference requests are required to verify installer via tests.

If the provider call or model response is unavailable/invalid, the Investigation Agent executes a bounded deterministic selection of read-only checks and logs `investigation_source: deterministic` plus a non-secret warning type. Source analytics and the final report still run.

## Test without any paid inference

```bash
python -m pytest -q tests/test_upgrade7_dynamic_investigation.py tests/test_upgrade6_ai_budget.py tests/test_llm_upgrade.py
npm --prefix frontend run build
```

These tests monkeypatch model gateway calls and never send HF traffic.

## Boundaries

This is a real model-directed **selection and execution** of a limited set of read-only analytical checks. It is **not** unrestricted dynamic LangGraph rewiring, external connector execution, arbitrary Python/SQL generation, self-modifying code, independent financial verification, or a guarantee that Qwen's qualitative conclusions are accurate. For safety, all numerical values shown in investigation artifacts are computed from trusted analytics artifacts rather than from model text.

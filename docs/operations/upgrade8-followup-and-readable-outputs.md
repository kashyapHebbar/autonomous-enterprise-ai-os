# Upgrade 8 — Evidence-grounded follow-up checks + plain-English output names

The original analytics, PDF/HTML report contents, storage keys, metadata, artifact
identifiers, downloads, lineage links, evaluation and UI URLs do not change.
The **dashboard display names only** are renamed, including historical runs:

| Previously | Dashboard label |
| --- | --- |
| Governed AI Investigation | AI Investigation Findings |
| Investigation Evidence (JSON) | Evidence Supporting the Findings |
| AI Analyst Briefing | AI Insights & Next Steps |
| Procurement Dashboard | Spending & Risk Dashboard |
| schema_profile.json | Dataset Overview |
| quality_report.json | Data Quality Check |
| procurement_analysis.json | Spending Figures & Findings |
| Evaluation artifact | Report Quality Check |
| Generated Python | Analysis Script (Technical) |

Historical filenames remain visible in Preview > Details > Original filename.
The supporting JSON evidence is grouped under **Facts & quality checks** instead
of being presented as an executive report. The filename/search backend is intact.

## Dynamic follow-up evidence (optional)

By default there is NO extra inference cost after installation. Upgrade 7's
3-call workflow behavior remains the default.

Enable with your existing Hugging Face token/settings and:

```bash
export AEAI_DYNAMIC_REASONING_ENABLED=true
export AEAI_REASONING_FOLLOWUPS_ENABLED=true
export AEAI_REASONING_MAX_FOLLOWUP_CHECKS=2
export AEAI_REASONING_REVIEW_ENABLED=false
export AEAI_LLM_MAX_CALLS_PER_RUN=4
make dev
```

With both planning and model-assisted briefing, up to **four** model requests:
planning, initial investigation selection, one follow-up decision, and briefing.
Actual requests depend on context, model availability and the current budget.
The optional legacy reviewer, if also enabled, can require a fifth call: raise
max calls explicitly only if needed and within your spending budget.

Qwen receives a bounded business question and verified aggregate facts from up
to 3 initial checks. It may STOP or select up to 2 *new* check names, referencing
valid evidence IDs. It cannot repeat checks, submit new arguments, read raw rows,
generate code or SQL, or execute external services. All additional results are
computed with the existing read-only deterministic executor. There is one extra
round, never an unbounded loop. If the model rejects, fails or hits its call/cost
budget, the initial investigation and rest of workflow still complete.

Audit: workflow Execution Activity contains `followup_status` (`expanded`,
`stopped`, `disabled`, `fallback`, `skipped`, `no_more_checks`), selected new checks
and evidence IDs. The original investigation JSON adds `followup`, new `steps`
with `phase: followup`, and `based_on_evidence_ids`. The report preview renders
new facts automatically from the added evidence steps.

**Important:** App-side token cost estimates are not provider bills or hard
Hugging Face spending caps; inspect provider billing separately.

## Offline installation/testing

```bash
python3 ~/Downloads/AEAI-Upgrade8-Apply.py
python -m pytest -q tests/test_upgrade8_followup.py tests/test_upgrade7_dynamic_investigation.py tests/test_upgrade6_ai_budget.py tests/test_llm_upgrade.py
npm --prefix frontend run build
```

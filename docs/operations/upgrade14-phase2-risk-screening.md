# Upgrade 14 — Phase 2: disk-backed risk screening

This feature is **separate from** the six-agent full analytical workflow and Upgrade 14 Phase 1's financial overview. It performs bounded rule-based pattern screening using SQLite spool tables, a managed local worker, and a user-initiated job API. No Hugging Face inference is performed by this worker.

## Launch / user flow

1. `make dev` starts API, workflow worker, monitoring worker, and **risk worker** locally. Docker Compose includes a separate `risk-worker` service sharing a single-host bind mount, primarily for development.
2. Open `/app/scale`, choose an authorized CSV investigation, then click **Start risk screening**.
3. The UI polls `GET /scaling/runs/{run_id}/risk-scan` every 2.5 seconds. Start, cancel and resume are authenticated workspace-scoped POST endpoints.
4. A cancellation is cooperative at checkpoint boundaries (500 source records); a cancelled/interrupted scan can resume from its last committed checkpoint, provided the source file fingerprint is unchanged. Resumption skips previously committed CSV rows (O(checkpoint size) startup) and **does not re-add them**.
5. A crashed worker is eligible for recovery after a 120-second stale lease. The database is local SQLite; it is **not suitable for multi-host workers or network shares**. Deploy to shared databases/volumes only after replacing this spool with a durable distributed execution design.

## Supported signals (aggregate counts, not verified fraud)

- High-value amount outliers using a dataset-wide IQR fence, calculated from a disk-backed sorted amount index.
- Repeated supplier/category/date/amount *fingerprints* (potential duplicates, not confirmed invoice duplicates).
- Repeated invoice IDs **only if an actual invoice identifier column is present**. An ArcGIS `OBJECTID` or source transaction ID is not an invoice ID.
- Potential split-purchase groups: at least 3 positive, similarly sized purchases with the same supplier/category/day and a material combined value. These are only triage flags.

No raw transaction rows, supplier names or invoice strings are returned in responses; the disk store contains salted hashes of identifying fields and fixed-point amounts. The output records only aggregates. The SQLite file itself must be protected like potentially sensitive enterprise data; hashed categorical values may still be guessable. Not a substitute for role-based data access control.

## Limits and numerical semantics

- Default `AEAI_RISK_MAX_ROWS=2000000`, maximum 10 million; `AEAI_RISK_MAX_MIB=512` source MiB; `AEAI_RISK_MAX_DB_MIB=1024` SQLite MiB; `AEAI_RISK_MAX_SECONDS=1800` per worker session.
- Amount values are quantized to 4 decimal places using `Decimal` and bankers rounding. Transaction values above 10 million source units are excluded as invalid for arithmetic safety; this is a screening-specific limitation, not a valid reason to discard those transactions in financial accounting.
- Negative/zero amounts contribute to high-value quartile calculations, but split-pattern groups require positive amounts.
- Scans have a **source consistency fingerprint** (size, inode, mtime and sampled beginning/end content). This is a practical integrity guard, not a cryptographic full-file verification; if source changes mid-scan, the final consistency guard refuses completion.
- Progress percentage is approximate, based on file-buffer position; row count is the authoritative progress metric. At 100% the scan is truly completed.
- SQLite disk size is measured using database page counts; WAL and ancillary files also consume disk space. Monitor actual disk usage.
- Small groups are not returned individually and raw matched transactions are never displayed; counts of signal groups are still aggregate disclosures governed by workspace permissions.

## Verification and recovery

```bash
AEAI_LLM_ENABLED=false python -m pytest -q tests/test_upgrade14_phase2_risk_screening.py
```

The feature stores jobs in `artifacts/aeai-risk-scans.db` by default. Back up this database together with its WAL/SHM files using a consistent SQLite backup procedure when workers are stopped. API and worker must use the same `AEAI_RISK_DB_PATH` and filesystem. Worker command for diagnosis: `PYTHONPATH=src python scripts/run_risk_worker.py --loop` (normally launched automatically; don't start a second copy unnecessarily).

### Known limitations

This phase does not offer unrestricted ML anomaly detection, arbitrary SQL, row-level investigation browsing, scheduled screening, production multi-host distributed queues, or automatic anomaly-to-fraud determination. The original full six-agent workflow is unchanged. Additional signals must be independently validated against known ground truth before use in consequential decisions.

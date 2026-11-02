"""Checkpointed, disk-backed *screening* for potential procurement patterns.

No raw supplier names, invoice numbers, or transaction rows are returned to clients
or passed to LLMs. This is a bounded second-pass risk *screening*, not a fraud
verdict and not the in-memory six-agent anomaly engine.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

from aeai_os.analytics.kpis import _resolve_columns
from aeai_os.scaling.summary import ScalingError, _integer_setting, _money

SCALE = Decimal("10000")
CHECKPOINT = 500


def _now() -> float:
    return time.time()


def _db_path() -> Path:
    return (
        Path(os.environ.get("AEAI_RISK_DB_PATH", "artifacts/aeai-risk-scans.db"))
        .expanduser()
        .resolve()
    )


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    h = hashlib.sha256()
    h.update(f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ino}".encode())
    with path.open("rb") as src:
        h.update(src.read(65536))
        if stat.st_size > 65536:
            src.seek(max(0, stat.st_size - 65536))
            h.update(src.read(65536))
    return h.hexdigest()


def _hash(value: str, salt: str) -> str:
    return hashlib.sha256((salt + "\x00" + value.strip().casefold()).encode()).hexdigest()


def _amount_units(raw: object) -> int | None:
    amount = _money(raw)
    if amount is None or abs(amount) > Decimal("10000000"):
        return None
    return int((amount * SCALE).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def _connection(path: Path | None = None) -> sqlite3.Connection:
    p = path or _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.touch(mode=0o600)
    con = sqlite3.connect(str(p), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript("""
    CREATE TABLE IF NOT EXISTS scans (
      id TEXT PRIMARY KEY, run_id TEXT NOT NULL, org TEXT NOT NULL, workspace TEXT NOT NULL,
      source_path TEXT NOT NULL, source_signature TEXT NOT NULL,
      status TEXT NOT NULL, scanned INTEGER NOT NULL DEFAULT 0,
      valid INTEGER NOT NULL DEFAULT 0, invalid INTEGER NOT NULL DEFAULT 0,
      sum_units INTEGER NOT NULL DEFAULT 0, size_bytes INTEGER NOT NULL,
      bytes_read INTEGER NOT NULL DEFAULT 0, invoice_column INTEGER NOT NULL DEFAULT 0,
      worker_id TEXT, updated_at REAL NOT NULL, created_at REAL NOT NULL,
      result TEXT, error TEXT
    );
    CREATE INDEX IF NOT EXISTS scans_pending_idx ON scans(status,updated_at);
    CREATE INDEX IF NOT EXISTS scans_run_idx ON scans(run_id,created_at);
    CREATE TABLE IF NOT EXISTS risk_rows (
      scan_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
      supplier_hash TEXT NOT NULL, category_hash TEXT NOT NULL,
      day TEXT NOT NULL, invoice_hash TEXT NOT NULL, amount_units INTEGER NOT NULL,
      PRIMARY KEY(scan_id,ordinal)
    );
    CREATE INDEX IF NOT EXISTS risk_amount_idx ON risk_rows(scan_id,amount_units);
    CREATE INDEX IF NOT EXISTS risk_fingerprint_idx ON risk_rows(scan_id,supplier_hash,category_hash,day,amount_units);
    CREATE INDEX IF NOT EXISTS risk_invoice_idx ON risk_rows(scan_id,invoice_hash);
    """)  # noqa: E501
    return con


def _public(record: sqlite3.Row | dict) -> dict:
    r = dict(record)
    return {
        "id": r["id"],
        "run_id": r["run_id"],
        "status": r["status"],
        "rows_scanned": r["scanned"],
        "valid_amount_rows": r["valid"],
        "invalid_amount_rows": r["invalid"],
        "progress_percent": min(99, round(r["bytes_read"] * 100 / max(1, r["size_bytes"]), 1))
        if r["status"] not in ("completed",)
        else 100,
        "started_at": datetime.fromtimestamp(r["created_at"], UTC).isoformat(),
        "updated_at": datetime.fromtimestamp(r["updated_at"], UTC).isoformat(),
        "result": json.loads(r["result"]) if r["result"] else None,
        "error": r["error"],
    }


def start_scan(
    run_id: str, path: Path, org: str, workspace: str, *, db_path: Path | None = None
) -> dict:
    p = Path(path).resolve()
    if not p.is_file() or p.suffix.lower() != ".csv":
        raise ScalingError("Select a local CSV investigation to run screening.")
    info = p.stat()
    max_mib = _integer_setting("AEAI_RISK_MAX_MIB", 512, 1, 4096)
    if info.st_size > max_mib * 1024 * 1024:
        raise ScalingError(
            "CSV exceeds AEAI_RISK_MAX_MIB; use a smaller snapshot or explicitly raise the limit."
        )
    signature = _fingerprint(p)
    ts = _now()
    key = "risk_" + uuid.uuid4().hex
    con = _connection(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            """SELECT * FROM scans WHERE run_id=? AND org=? AND workspace=?
                AND status IN ('queued','running','cancel_requested') ORDER BY created_at DESC LIMIT 1""",  # noqa: E501
            (run_id, org, workspace),
        ).fetchone()
        if existing:
            con.commit()
            return _public(existing)
        con.execute(
            """INSERT INTO scans
            (id,run_id,org,workspace,source_path,source_signature,status,size_bytes,updated_at,created_at)
            VALUES (?,?,?,?,?,?,'queued',?,?,?)""",
            (key, run_id, org, workspace, str(p), signature, info.st_size, ts, ts),
        )
        row = con.execute("SELECT * FROM scans WHERE id=?", (key,)).fetchone()
        con.commit()
        return _public(row)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def latest_scan(
    run_id: str, org: str, workspace: str, *, db_path: Path | None = None
) -> dict | None:
    con = _connection(db_path)
    try:
        row = con.execute(
            """SELECT * FROM scans WHERE run_id=? AND org=? AND workspace=?
                              ORDER BY created_at DESC LIMIT 1""",
            (run_id, org, workspace),
        ).fetchone()
        return _public(row) if row else None
    finally:
        con.close()


def set_scan_action(
    run_id: str, scan_id: str, org: str, workspace: str, action: str, *, db_path: Path | None = None
) -> dict:
    if action not in ("cancel", "resume"):
        raise ScalingError("Unsupported screening action.")
    con = _connection(db_path)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM scans WHERE id=? AND run_id=? AND org=? AND workspace=?",
            (scan_id, run_id, org, workspace),
        ).fetchone()
        if row is None:
            raise KeyError("Risk scan not found")
        if action == "cancel":
            if row["status"] not in ("queued", "running", "cancel_requested"):
                raise ScalingError("Only waiting or running scans can be cancelled.")
            next_status = "cancel_requested" if row["status"] == "running" else "cancelled"
        else:
            if row["status"] not in ("cancelled", "failed", "interrupted"):
                raise ScalingError("Only cancelled or interrupted scans can be resumed.")
            if _fingerprint(Path(row["source_path"])) != row["source_signature"]:
                raise ScalingError(
                    "The source CSV has changed; start a new scan rather than resuming."
                )
            next_status = "queued"
        con.execute(
            "UPDATE scans SET status=?,error=NULL,updated_at=? WHERE id=?",
            (next_status, _now(), scan_id),
        )
        updated = con.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        con.commit()
        return _public(updated)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _claim(con: sqlite3.Connection, worker_id: str) -> sqlite3.Row | None:
    con.execute("BEGIN IMMEDIATE")
    stale = _now() - 120
    # When a worker dies mid-scan, restart from its last committed checkpoint.
    con.execute(
        "UPDATE scans SET status='queued',worker_id=NULL WHERE status='running' AND updated_at<?",
        (stale,),
    )
    con.execute(
        "UPDATE scans SET status='cancelled',worker_id=NULL WHERE status='cancel_requested' AND updated_at<?",  # noqa: E501
        (stale,),
    )
    row = con.execute(
        "SELECT * FROM scans WHERE status='queued' ORDER BY created_at LIMIT 1"
    ).fetchone()
    if row:
        con.execute(
            "UPDATE scans SET status='running',worker_id=?,updated_at=? WHERE id=? AND status='queued'",  # noqa: E501
            (worker_id, _now(), row["id"]),
        )
        row = con.execute("SELECT * FROM scans WHERE id=?", (row["id"],)).fetchone()
    con.commit()
    return row


def _percentile(con: sqlite3.Connection, scan_id: str, n: int, p: float) -> int:
    pos = (n - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    a = con.execute(
        "SELECT amount_units FROM risk_rows WHERE scan_id=? ORDER BY amount_units LIMIT 1 OFFSET ?",
        (scan_id, lo),
    ).fetchone()[0]
    if lo == hi:
        return int(a)
    b = con.execute(
        "SELECT amount_units FROM risk_rows WHERE scan_id=? ORDER BY amount_units LIMIT 1 OFFSET ?",
        (scan_id, hi),
    ).fetchone()[0]
    return round(a + (b - a) * (pos - lo))


def _finalize(con: sqlite3.Connection, job: sqlite3.Row) -> dict:
    scan_id = job["id"]
    n = int(job["valid"])
    stored = con.execute(
        "SELECT COUNT(*),COALESCE(SUM(amount_units),0) FROM risk_rows WHERE scan_id=?", (scan_id,)
    ).fetchone()
    if stored[0] != n or stored[1] != job["sum_units"]:
        raise ScalingError("Disk-backed transaction ledger did not reconcile; results discarded.")
    q1 = _percentile(con, scan_id, n, 0.25) if n >= 4 else None
    q3 = _percentile(con, scan_id, n, 0.75) if n >= 4 else None
    limit = int(q3 + 1.5 * (q3 - q1)) if q1 is not None and q3 is not None else None
    high = (
        con.execute(
            "SELECT COUNT(*) FROM risk_rows WHERE scan_id=? AND amount_units>?", (scan_id, limit)
        ).fetchone()[0]
        if limit is not None
        else 0
    )
    duplicate = con.execute(
        """SELECT COUNT(*), COALESCE(SUM(n),0) FROM (
        SELECT COUNT(*) n FROM risk_rows WHERE scan_id=? AND day<>''
        GROUP BY supplier_hash,category_hash,day,amount_units HAVING n>1
    )""",
        (scan_id,),
    ).fetchone()
    invoice = (0, 0)
    if job["invoice_column"]:
        invoice = con.execute(
            """SELECT COUNT(*),COALESCE(SUM(n),0) FROM (
            SELECT COUNT(*) n FROM risk_rows WHERE scan_id=? AND invoice_hash<>''
            GROUP BY invoice_hash HAVING n>1
        )""",
            (scan_id,),
        ).fetchone()
    split = con.execute(
        """SELECT COUNT(*),COALESCE(SUM(n),0) FROM (
        SELECT COUNT(*) n,MIN(amount_units) lo,MAX(amount_units) hi, SUM(amount_units) total
        FROM risk_rows WHERE scan_id=? AND day<>'' AND amount_units>0
        GROUP BY supplier_hash,category_hash,day
        HAVING n>=3 AND hi*100<=lo*115 AND total>=?
    )""",
        (scan_id, max(0, (q3 or 0) * 2)),
    ).fetchone()
    return {
        "analysis_type": "disk_backed_pattern_screening",
        "coverage": "full_source_rule_based_screening_not_fraud_determination",
        "metrics": {
            "rows_scanned": job["scanned"],
            "valid_amount_rows": n,
            "invalid_amount_rows": job["invalid"],
            "total_amount_source_units": round(job["sum_units"] / 10000, 4),
        },
        "signals": {
            "unusually_high_amount_transactions": high,
            "repeated_transaction_pattern_groups": duplicate[0],
            "transactions_in_repeated_patterns": duplicate[1],
            "repeated_invoice_identifier_groups": invoice[0],
            "transactions_in_repeated_invoice_groups": invoice[1],
            "possible_split_pattern_groups": split[0],
            "transactions_in_split_patterns": split[1],
        },
        "thresholds": {
            "amount_iqr_upper_source_units": round(limit / 10000, 4) if limit is not None else None
        },
        "invoice_identifier_available": bool(job["invoice_column"]),
        "verification": "Exact fixed-point amount total and row count reconciled with the SQLite spool.",  # noqa: E501
        "limitations": [
            "Flags are potential patterns, not evidence of fraud or policy violation.",
            "Repeated supplier/category/day/amount values do not prove duplicate invoices.",
            "The split-purchase signal is heuristic and requires manual investigation.",
            "Without a true invoice field, invoice duplication is not assessed.",
            "Only the supported read-only CSV screening rules were executed; no AI model was called.",  # noqa: E501
        ],
        "hugging_face_requests": 0,
    }


def _run_job(con: sqlite3.Connection, job: sqlite3.Row, worker_id: str, stop: Callable[[], bool]):
    scan_id = job["id"]
    path = Path(job["source_path"])
    if not path.is_file() or _fingerprint(path) != job["source_signature"]:
        raise ScalingError("Source data changed or disappeared; create a new scan.")
    max_rows = _integer_setting("AEAI_RISK_MAX_ROWS", 2_000_000, 1, 10_000_000)
    max_seconds = _integer_setting("AEAI_RISK_MAX_SECONDS", 1800, 10, 86400)
    max_db_mib = _integer_setting("AEAI_RISK_MAX_DB_MIB", 1024, 10, 16384)
    started = time.monotonic()
    processed = int(job["scanned"])
    valid = int(job["valid"])
    invalid = int(job["invalid"])
    total = int(job["sum_units"])
    invoice_available = int(job["invoice_column"])
    batch = []

    def commit_batch():
        nonlocal batch
        con.execute("BEGIN IMMEDIATE")
        active = con.execute("SELECT status,worker_id FROM scans WHERE id=?", (scan_id,)).fetchone()
        if (
            not active
            or active["worker_id"] != worker_id
            or active["status"] not in ("running", "cancel_requested")
        ):
            con.rollback()
            raise ScalingError("Worker lease was lost; partial progress is preserved.")
        if batch:
            con.executemany(
                """INSERT INTO risk_rows(scan_id,ordinal,supplier_hash,category_hash,day,invoice_hash,amount_units)
                        VALUES (?,?,?,?,?,?,?)""",  # noqa: E501
                batch,
            )
        con.execute(
            """UPDATE scans SET scanned=?,valid=?,invalid=?,sum_units=?,bytes_read=?,invoice_column=?,
                       updated_at=? WHERE id=?""",  # noqa: E501
            (
                processed,
                valid,
                invalid,
                total,
                min(path.stat().st_size, byte_pos),
                invoice_available,
                _now(),
                scan_id,
            ),
        )
        con.commit()
        batch = []

    byte_pos = 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        fields = [f.strip() for f in headers]
        if not fields or any(not f for f in fields) or len(set(fields)) != len(fields):
            raise ScalingError("CSV headers contain duplicates or missing values.")
        roles = _resolve_columns(fields)
        if not {"supplier", "category", "amount"}.issubset(roles):
            raise ScalingError("Risk screening requires supplier, category and amount columns.")
        raw = dict(zip(fields, headers, strict=True))
        invoice_available = int("invoice_id" in roles)
        if processed:
            for _ in range(processed):
                if next(reader, None) is None:
                    raise ScalingError("Saved checkpoint extends beyond the CSV; cannot resume.")
        for row in reader:
            if stop():
                commit_batch()
                con.execute(
                    "UPDATE scans SET status=?,worker_id=NULL,updated_at=? WHERE id=?",
                    ("interrupted", _now(), scan_id),
                )
                return
            if processed % CHECKPOINT == 0:
                status = con.execute("SELECT status FROM scans WHERE id=?", (scan_id,)).fetchone()[
                    "status"
                ]
                if status == "cancel_requested":
                    commit_batch()
                    con.execute(
                        "UPDATE scans SET status=?,worker_id=NULL,updated_at=? WHERE id=?",
                        ("cancelled", _now(), scan_id),
                    )
                    return
                if time.monotonic() - started > max_seconds:
                    commit_batch()
                    con.execute(
                        "UPDATE scans SET status=?,worker_id=NULL,updated_at=? WHERE id=?",
                        ("interrupted", _now(), scan_id),
                    )
                    return
            processed += 1
            if processed > max_rows:
                raise ScalingError(
                    "Maximum risk scan rows reached; partial progress retained, no result published."  # noqa: E501
                )
            amount = _amount_units(row.get(raw[roles["amount"]]))
            if amount is None:
                invalid += 1
            else:
                valid += 1
                total += amount
                salt = scan_id
                s = _hash(str(row.get(raw[roles["supplier"]]) or ""), salt)
                c = _hash(str(row.get(raw[roles["category"]]) or ""), salt)
                day = str(row.get(raw[roles["date"]]) or "").strip()[:10] if "date" in roles else ""
                inv = (
                    _hash(str(row.get(raw[roles["invoice_id"]]) or ""), salt)
                    if invoice_available and str(row.get(raw[roles["invoice_id"]]) or "").strip()
                    else ""
                )
                batch.append((scan_id, processed, s, c, day, inv, amount))
            if processed % CHECKPOINT == 0:
                byte_pos = stream.buffer.tell()
                commit_batch()
                if (
                    con.execute("PRAGMA page_count").fetchone()[0]
                    * con.execute("PRAGMA page_size").fetchone()[0]
                ) > max_db_mib * 1024 * 1024:
                    raise ScalingError(
                        "Risk screening spool reached its storage limit; data saved for inspection."
                    )
        byte_pos = path.stat().st_size
        commit_batch()
    if _fingerprint(path) != job["source_signature"]:
        raise ScalingError("Source changed during screening; result not published.")
    current = con.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    result = _finalize(con, current)
    con.execute("BEGIN IMMEDIATE")
    state = con.execute("SELECT status,worker_id FROM scans WHERE id=?", (scan_id,)).fetchone()
    if state["status"] == "cancel_requested":
        con.execute(
            "UPDATE scans SET status=?,worker_id=NULL,updated_at=? WHERE id=?",
            ("cancelled", _now(), scan_id),
        )
    elif state["status"] == "running" and state["worker_id"] == worker_id:
        con.execute(
            """UPDATE scans SET status='completed',worker_id=NULL,result=?,error=NULL,
                       bytes_read=size_bytes,updated_at=? WHERE id=?""",
            (json.dumps(result), _now(), scan_id),
        )
    con.commit()


def process_next(
    *,
    db_path: Path | None = None,
    worker_id: str | None = None,
    stop: Callable[[], bool] = lambda: False,
) -> str | None:
    con = _connection(db_path)
    who = worker_id or ("risk-worker-" + str(os.getpid()))
    try:
        job = _claim(con, who)
        if not job:
            return None
        try:
            _run_job(con, job, who, stop)
        except (ScalingError, sqlite3.Error, OSError, csv.Error, OverflowError, ValueError) as exc:
            con.rollback()
            con.execute(
                """UPDATE scans SET status='failed',worker_id=NULL,error=?,updated_at=?
                           WHERE id=? AND worker_id=?""",
                (str(exc)[:300], _now(), job["id"], who),
            )
        return job["id"]
    finally:
        con.close()

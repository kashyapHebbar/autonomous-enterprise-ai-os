"""SQLite-backed monitor definitions, atomic due-job claiming and durable alerts.

The scheduler is a separate opt-in process; API reads never dispatch work.
This local SQLite control plane is deliberately independent of the run database.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

INTERVALS = {"hourly": 3600, "daily": 86400, "weekly": 604800}
ALERT_STATES = {"open", "acknowledged", "resolved"}


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class MonitorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Monitoring database must not be a symbolic link.")
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=20000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
              CREATE TABLE IF NOT EXISTS monitors (
                id TEXT PRIMARY KEY, organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                name TEXT NOT NULL, task TEXT NOT NULL, source_id TEXT NOT NULL,
                interval TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                only_on_change INTEGER NOT NULL DEFAULT 1, ai_escalation INTEGER NOT NULL DEFAULT 0,
                anomaly_limit INTEGER NOT NULL DEFAULT 1, spend_change_pct REAL NOT NULL DEFAULT 20,
                minimum_completeness REAL NOT NULL DEFAULT 0.95,
                last_fingerprint TEXT, last_checked_at TEXT, last_run_id TEXT,
                next_due_at TEXT NOT NULL, force_once INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
              );
              CREATE INDEX IF NOT EXISTS idx_monitors_due ON monitors(enabled, next_due_at);
              CREATE TABLE IF NOT EXISTS monitor_runs (
                id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
                organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                started_at TEXT NOT NULL, finished_at TEXT,
                status TEXT NOT NULL, fingerprint TEXT, run_id TEXT,
                metrics_json TEXT NOT NULL DEFAULT '{}', ai_review_json TEXT NOT NULL DEFAULT '{}', error TEXT
              );
              CREATE INDEX IF NOT EXISTS idx_monitor_runs ON monitor_runs(monitor_id, started_at);
              CREATE TABLE IF NOT EXISTS monitoring_alerts (
                id TEXT PRIMARY KEY, monitor_id TEXT NOT NULL REFERENCES monitors(id),
                organization_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                dispatch_id TEXT NOT NULL, run_id TEXT, rule TEXT NOT NULL,
                severity TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(monitor_id, dispatch_id, rule)
              );
              CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON monitoring_alerts(organization_id, workspace_id, status);
              CREATE TABLE IF NOT EXISTS monitor_worker (
                worker_id TEXT PRIMARY KEY, heartbeat_at TEXT NOT NULL
              );
            """)  # noqa: E501
        if os.name == "posix":
            os.chmod(self.path, 0o600)

    @staticmethod
    def _row(row):
        if row is None:
            return None
        data = dict(row)
        for key in ("enabled", "only_on_change", "ai_escalation", "force_once"):
            if key in data:
                data[key] = bool(data[key])
        for key in ("metrics_json", "evidence_json", "ai_review_json"):
            if key in data:
                data[key.removesuffix("_json")] = json.loads(data.pop(key))
        return data

    def create(
        self,
        *,
        organization_id: str,
        workspace_id: str,
        name: str,
        task: str,
        source_id: str,
        interval: str,
        only_on_change: bool = True,
        ai_escalation: bool = False,
        anomaly_limit: int = 1,
        spend_change_pct: float = 20,
        minimum_completeness: float = 0.95,
    ) -> dict:
        if interval not in INTERVALS:
            raise ValueError("Unsupported monitoring interval.")
        now = utcnow()
        monitor_id = f"mon_{uuid4().hex}"
        with self._connect() as db:
            count = db.execute(
                "SELECT count(*) FROM monitors WHERE organization_id=? AND workspace_id=?",
                (organization_id, workspace_id),
            ).fetchone()[0]
            if count >= 40:
                raise ValueError("Workspace monitoring limit (40) reached.")
            db.execute(
                """INSERT INTO monitors (id,organization_id,workspace_id,name,task,source_id,
                      interval,enabled,only_on_change,ai_escalation,anomaly_limit,spend_change_pct,
                      minimum_completeness,next_due_at,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
                (
                    monitor_id,
                    organization_id,
                    workspace_id,
                    name,
                    task,
                    source_id,
                    interval,
                    int(only_on_change),
                    int(ai_escalation),
                    anomaly_limit,
                    spend_change_pct,
                    minimum_completeness,
                    now,
                    now,
                    now,
                ),
            )
        return self.get(monitor_id, organization_id, workspace_id)

    def get(self, monitor_id: str, org: str, workspace: str) -> dict | None:
        with self._connect() as db:
            return self._row(
                db.execute(
                    "SELECT * FROM monitors WHERE id=? AND organization_id=? AND workspace_id=?",
                    (monitor_id, org, workspace),
                ).fetchone()
            )

    def list(self, org: str, workspace: str) -> list[dict]:
        with self._connect() as db:
            return [
                self._row(row)
                for row in db.execute(
                    "SELECT * FROM monitors WHERE organization_id=? AND workspace_id=? ORDER BY created_at DESC",  # noqa: E501
                    (org, workspace),
                ).fetchall()
            ]

    def set_enabled(self, monitor_id: str, org: str, workspace: str, enabled: bool) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE monitors SET enabled=?, updated_at=? WHERE id=? AND organization_id=? AND workspace_id=?",  # noqa: E501
                (int(enabled), utcnow(), monitor_id, org, workspace),
            )
            return bool(cursor.rowcount)

    def trigger(self, monitor_id: str, org: str, workspace: str) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE monitors SET next_due_at=?, force_once=1, updated_at=? "
                "WHERE id=? AND organization_id=? AND workspace_id=? AND enabled=1",
                (utcnow(), utcnow(), monitor_id, org, workspace),
            )
            return bool(cursor.rowcount)

    def heartbeat(self, worker_id: str):
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO monitor_worker(worker_id,heartbeat_at) VALUES(?,?)",
                (worker_id, utcnow()),
            )

    def latest_heartbeat(self) -> str | None:
        with self._connect() as db:
            result = db.execute("SELECT max(heartbeat_at) FROM monitor_worker").fetchone()[0]
            return result

    def claim(self, *, limit: int = 2, now: str | None = None) -> list[dict]:
        """Atomic claim across processes. Advance next_due before executing (at-most-once)."""
        now = now or utcnow()
        claimed = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                rows = db.execute(
                    "SELECT * FROM monitors WHERE enabled=1 AND next_due_at<=? "
                    "ORDER BY next_due_at LIMIT ?",
                    (now, max(1, min(limit, 5))),
                ).fetchall()
                for row in rows:
                    record = self._row(row)
                    next_due = (
                        _dt(now) + timedelta(seconds=INTERVALS[record["interval"]])
                    ).isoformat()
                    dispatch_id = f"dispatch_{uuid4().hex}"
                    db.execute(
                        "UPDATE monitors SET next_due_at=?,force_once=0,updated_at=? WHERE id=?",
                        (next_due, now, record["id"]),
                    )
                    db.execute(
                        """INSERT INTO monitor_runs(id,monitor_id,organization_id,workspace_id,
                                   started_at,status) VALUES(?,?,?,?,?,'running')""",
                        (
                            dispatch_id,
                            record["id"],
                            record["organization_id"],
                            record["workspace_id"],
                            now,
                        ),
                    )
                    record["dispatch_id"] = dispatch_id
                    claimed.append(record)
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        return claimed

    def finish(
        self,
        monitor: dict,
        *,
        status: str,
        fingerprint: str | None = None,
        run_id: str | None = None,
        metrics: dict | None = None,
        ai_review: dict | None = None,
        error: str | None = None,
    ):
        if status not in {"completed", "skipped", "failed"}:
            raise ValueError("Invalid monitor dispatch status")
        now = utcnow()
        with self._connect() as db:
            db.execute(
                """UPDATE monitor_runs SET finished_at=?,status=?,fingerprint=?,
                          run_id=?,metrics_json=?,ai_review_json=?,error=? WHERE id=? AND status='running'""",  # noqa: E501
                (
                    now,
                    status,
                    fingerprint,
                    run_id,
                    json.dumps(metrics or {}),
                    json.dumps(ai_review or {}),
                    str(error or "")[:300] or None,
                    monitor["dispatch_id"],
                ),
            )
            db.execute(
                """UPDATE monitors SET last_checked_at=?,last_run_id=COALESCE(?,last_run_id),
                          last_fingerprint=CASE WHEN ?='completed' THEN ? ELSE last_fingerprint END,
                          updated_at=? WHERE id=?""",
                (now, run_id, status, fingerprint, now, monitor["id"]),
            )

    def last_completed(self, monitor_id: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM monitor_runs WHERE monitor_id=? AND status='completed' "
                "ORDER BY finished_at DESC LIMIT 1",
                (monitor_id,),
            ).fetchone()
            return self._row(row)

    def history(self, monitor_id: str, org: str, workspace: str) -> list[dict]:
        if self.get(monitor_id, org, workspace) is None:
            return []
        with self._connect() as db:
            return [
                self._row(row)
                for row in db.execute(
                    "SELECT * FROM monitor_runs WHERE monitor_id=? ORDER BY started_at DESC LIMIT 30",  # noqa: E501
                    (monitor_id,),
                ).fetchall()
            ]

    def create_alert(
        self,
        monitor: dict,
        *,
        rule: str,
        severity: str,
        title: str,
        description: str,
        evidence: dict,
        run_id: str | None,
    ):
        now = utcnow()
        with self._connect() as db:
            db.execute(
                """INSERT OR IGNORE INTO monitoring_alerts (
                         id,monitor_id,organization_id,workspace_id,dispatch_id,run_id,
                         rule,severity,title,description,evidence_json,status,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,'open',?,?)""",
                (
                    f"alert_{uuid4().hex}",
                    monitor["id"],
                    monitor["organization_id"],
                    monitor["workspace_id"],
                    monitor["dispatch_id"],
                    run_id,
                    rule,
                    severity,
                    title[:160],
                    description[:400],
                    json.dumps(evidence),
                    now,
                    now,
                ),
            )

    def alerts(self, org: str, workspace: str, *, state: str | None = None) -> list[dict]:
        if state is not None and state not in ALERT_STATES:
            raise ValueError("Invalid alert state")
        with self._connect() as db:
            clause = " AND status=?" if state else ""
            params = (org, workspace, state) if state else (org, workspace)
            return [
                self._row(row)
                for row in db.execute(
                    "SELECT * FROM monitoring_alerts WHERE organization_id=? AND workspace_id=?"
                    + clause
                    + " ORDER BY created_at DESC LIMIT 200",
                    params,
                ).fetchall()
            ]

    def update_alert(self, alert_id: str, org: str, workspace: str, state: str) -> bool:
        if state not in ALERT_STATES:
            raise ValueError("Invalid alert state")
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE monitoring_alerts SET status=?,updated_at=? "
                "WHERE id=? AND organization_id=? AND workspace_id=?",
                (state, utcnow(), alert_id, org, workspace),
            )
            return bool(cursor.rowcount)

    def summary(self, org: str, workspace: str) -> dict:
        monitors = self.list(org, workspace)
        alerts = self.alerts(org, workspace)
        heartbeat = self.latest_heartbeat()
        recent_worker = bool(heartbeat and (_dt(utcnow()) - _dt(heartbeat)).total_seconds() < 180)
        return {
            "monitor_count": len(monitors),
            "enabled_monitors": sum(m["enabled"] for m in monitors),
            "open_alerts": sum(a["status"] == "open" for a in alerts),
            "critical_alerts": sum(
                a["status"] == "open" and a["severity"] == "high" for a in alerts
            ),
            "worker_online": recent_worker,
            "worker_last_seen": heartbeat,
            "recent_alerts": alerts[:5],
            "auto_ai_enabled": bool(
                os.getenv("AEAI_MONITOR_AI_ESCALATION_ENABLED", "").lower() in {"true", "1", "yes"}
            ),
            "note": "A separate monitoring worker is required. AI escalation is opt-in and billed via Hugging Face.",  # noqa: E501
        }

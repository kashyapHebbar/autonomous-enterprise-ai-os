"""Single-host workflow-worker liveness signal.

Local file is not a distributed worker registry. For multi-host deployments
use a shared operational store / external orchestrator health probes.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


def path_for_heartbeat() -> Path:
    return Path(os.getenv("AEAI_WORKFLOW_HEARTBEAT_PATH", "artifacts/aeai-workflow-heartbeat.json"))


def write_heartbeat(*, worker_id: str, active: bool, path: Path | None = None) -> None:
    destination = path or path_for_heartbeat()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Heartbeat target must not be a symlink")
    data = {
        "worker_id": worker_id,
        "last_seen": datetime.now(UTC).isoformat(),
        "active": active,
    }
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, prefix=".aeai-worker-", delete=False
        ) as handle:
            temp_name = handle.name
            os.chmod(handle.name, 0o600)
            json.dump(data, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def read_heartbeat(*, path: Path | None = None, timeout_seconds: int = 20) -> dict:
    destination = path or path_for_heartbeat()
    missing = {"online": False, "active": False, "last_seen": None}
    try:
        if destination.is_symlink():
            return missing
        data = json.loads(destination.read_text(encoding="utf-8"))
        when = datetime.fromisoformat(data["last_seen"])
        if when.tzinfo is None:
            return missing
        age = datetime.now(UTC) - when.astimezone(UTC)
        online = timedelta(seconds=-5) <= age <= timedelta(seconds=timeout_seconds)
        return {
            "online": online,
            "active": bool(data.get("active")) if online else False,
            "last_seen": data["last_seen"],
        }
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return missing

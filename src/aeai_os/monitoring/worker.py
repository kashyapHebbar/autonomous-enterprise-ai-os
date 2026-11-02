"""Opt-in monitoring worker. Run in a separate terminal from FastAPI.

Examples:
  python -m aeai_os.monitoring.worker --once
  python -m aeai_os.monitoring.worker --loop

Monitoring deliberately does not run inside Uvicorn's process to avoid duplicate
jobs from reload/multiple web workers. A crashed claimed job is recorded as
stale and is never silently replayed.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(description="AEAI OS opt-in monitoring worker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--once", action="store_true")
    group.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    from aeai_os.connectors import (
        build_connector_installation_repository,
        build_default_connector_registry,
        build_default_credential_provider_registry,
    )
    from aeai_os.data.sources import DataSourceRegistry
    from aeai_os.monitoring.engine import process_due
    from aeai_os.monitoring.store import MonitorStore
    from aeai_os.runs.factory import build_run_repository
    from aeai_os.settings import get_settings
    from aeai_os.storage import build_artifact_store

    # Default to zero HF calls, regardless of how the interactive backend runs.
    # Scheduled HF escalation is a separate future approval-controlled feature.
    os.environ["AEAI_LLM_ENABLED"] = "false"
    settings = get_settings()
    if settings.run_repository_backend != "sqlalchemy":
        raise SystemExit("Monitoring requires AEAI_RUN_REPOSITORY_BACKEND=sqlalchemy")
    store = MonitorStore(os.getenv("AEAI_MONITOR_DB_PATH", "artifacts/aeai-monitoring.db"))
    repository = build_run_repository(settings)
    artifact_root = Path(settings.artifact_root)
    artifact_store = build_artifact_store(settings, artifact_root=artifact_root)
    connectors = build_default_connector_registry(
        settings,
        installation_store=build_connector_installation_repository(settings),
        credential_resolver=build_default_credential_provider_registry(),
    )
    worker_id = f"local_worker_{uuid4().hex[:12]}"
    while True:
        store.heartbeat(worker_id)
        # Re-read the restart-safe source catalog on each poll so newly registered
        # datasets are picked up without restarting this worker.
        registry = DataSourceRegistry(connector_registry=connectors)
        results = process_due(
            store=store,
            registry=registry,
            repository=repository,
            artifact_store=artifact_store,
            artifact_root=artifact_root,
        )
        for result in results:
            print(f"Monitoring: {result['status']} / run={result.get('run_id', '—')}", flush=True)
        if args.once:
            return
        time.sleep(30)


if __name__ == "__main__":
    main()

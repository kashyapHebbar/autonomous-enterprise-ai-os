"""A continuously running workflow worker with a truthful liveness heartbeat.

Use as a managed server process, not from an HTTP request. Database and artifact
storage must be identical to those used by the API. Serial per-worker execution
prevents concurrent runs on constrained local machines.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from aeai_os.connectors import (
        build_connector_installation_repository,
        build_default_connector_registry,
        build_default_credential_provider_registry,
    )
    from aeai_os.operations.heartbeat import write_heartbeat
    from aeai_os.runs.factory import build_run_repository
    from aeai_os.settings import get_settings
    from aeai_os.storage import build_artifact_store
    from aeai_os.workflows.queue import build_workflow_queue
    from aeai_os.workflows.worker import WorkflowWorker

    parser = argparse.ArgumentParser(description="AEAI managed workflow worker")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--max-jobs", type=int, default=None)
    args = parser.parse_args()
    if args.poll_interval < 0.2:
        parser.error("--poll-interval must be at least 0.2 seconds")
    settings = get_settings()
    if settings.run_repository_backend != "sqlalchemy":
        parser.error("Managed workflow worker requires persistent SQLAlchemy repository")
    repo = build_run_repository(settings)
    queue = build_workflow_queue(settings, repo)
    registry = build_default_connector_registry(
        settings,
        installation_store=build_connector_installation_repository(settings),
        credential_resolver=build_default_credential_provider_registry(),
    )
    worker_id = "managed_" + uuid4().hex[:12]
    worker = WorkflowWorker(
        repository=repo,
        artifact_root=settings.artifact_root,
        worker_id=worker_id,
        queue=queue,
        artifact_store=build_artifact_store(settings),
        connector_registry=registry,
        claim_timeout_seconds=settings.workflow_queue_timeout_seconds,
    )
    stopping = threading.Event()
    busy = threading.Event()

    def stop(*_args):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def heartbeat():
        while not stopping.is_set():
            write_heartbeat(worker_id=worker_id, active=busy.is_set())
            stopping.wait(3)

    pulse = threading.Thread(target=heartbeat, daemon=True)
    pulse.start()
    processed = 0
    print("AEAI workflow worker online. Waiting for queued jobs…", flush=True)
    try:
        while not stopping.is_set():
            busy.set()
            try:
                job = worker.process_next_job()
            except Exception:
                logging.exception("Workflow worker could not process a job")
                stopping.wait(3)
                continue
            finally:
                busy.clear()
            if job is None:
                stopping.wait(args.poll_interval)
                continue
            print(f"Workflow {job.run_id}: {job.status} (job {job.id})", flush=True)
            processed += 1
            if args.max_jobs is not None and processed >= args.max_jobs:
                break
    finally:
        stopping.set()
        pulse.join(timeout=4)
        # Heartbeat left on disk becomes offline after freshness TTL.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

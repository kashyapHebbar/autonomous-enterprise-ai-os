from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    from aeai_os.runs.factory import build_run_repository
    from aeai_os.settings import get_settings
    from aeai_os.storage import build_artifact_store
    from aeai_os.workflows.queue import build_workflow_queue
    from aeai_os.workflows.worker import WorkflowWorker

    parser = argparse.ArgumentParser(description="Process one queued workflow job.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Continuously poll for queued workflow jobs.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=5.0,
        help="Seconds to wait between empty queue polls when --loop is enabled.",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Optional maximum jobs to process before exiting.",
    )
    parser.add_argument("--claim-timeout-seconds", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    repository = build_run_repository(settings)
    queue = build_workflow_queue(settings, repository)
    artifact_store = build_artifact_store(settings)
    worker = WorkflowWorker(
        repository=repository,
        artifact_root=settings.artifact_root,
        worker_id=args.worker_id,
        queue=queue,
        claim_timeout_seconds=(
            args.claim_timeout_seconds
            if args.claim_timeout_seconds is not None
            else settings.workflow_queue_timeout_seconds
        ),
        artifact_store=artifact_store,
    )
    if args.loop:
        processed_count = 0
        while True:
            job = worker.process_next_job()
            if job is None:
                time.sleep(max(args.poll_interval, 0.1))
                continue
            _print_job(job)
            processed_count += 1
            if args.max_jobs is not None and processed_count >= args.max_jobs:
                return 0

    job = worker.process_next_job()
    if job is None:
        print("No queued workflow jobs.")
        return 0

    _print_job(job)
    return 0


def _print_job(job) -> None:
    print(
        "Processed workflow job "
        f"{job.id}: run_id={job.run_id} workflow={job.workflow_name} "
        f"status={job.status} attempts={job.attempt_count}/{job.max_attempts}"
    )
    if job.error_summary:
        print(f"Last error: {job.error_summary}")


if __name__ == "__main__":
    raise SystemExit(main())

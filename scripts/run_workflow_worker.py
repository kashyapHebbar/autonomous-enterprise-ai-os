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
    from aeai_os.workflows.queue import build_workflow_queue
    from aeai_os.workflows.worker import WorkflowWorker

    parser = argparse.ArgumentParser(description="Process one queued workflow job.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--loop", action="store_true", help="Continuously poll for queued jobs.")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--claim-timeout-seconds", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    repository = build_run_repository(settings)
    queue = build_workflow_queue(settings, repository)
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
    )

    while True:
        job = worker.process_next_job()
        if job is None:
            print("No queued workflow jobs.")
            if not args.loop:
                return 0
            time.sleep(args.poll_interval)
            continue

        print(
            "Processed workflow job "
            f"{job.id}: run_id={job.run_id} workflow={job.workflow_name} "
            f"status={job.status} attempts={job.attempt_count}/{job.max_attempts}"
        )
        if job.error_summary:
            print(f"Last error: {job.error_summary}")
        if not args.loop:
            return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

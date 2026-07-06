from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    from aeai_os.runs.factory import build_run_repository
    from aeai_os.settings import get_settings
    from aeai_os.storage import build_artifact_store
    from aeai_os.workflows.worker import WorkflowWorker

    parser = argparse.ArgumentParser(description="Process one queued workflow job.")
    parser.add_argument("--worker-id", default=None)
    args = parser.parse_args()

    settings = get_settings()
    repository = build_run_repository(settings)
    artifact_store = build_artifact_store(settings)
    worker = WorkflowWorker(
        repository=repository,
        artifact_root=settings.artifact_root,
        worker_id=args.worker_id,
        artifact_store=artifact_store,
    )
    job = worker.process_next_job()
    if job is None:
        print("No queued workflow jobs.")
        return 0

    print(
        "Processed workflow job "
        f"{job.id}: run_id={job.run_id} workflow={job.workflow_name} "
        f"status={job.status} attempts={job.attempt_count}/{job.max_attempts}"
    )
    if job.error_summary:
        print(f"Last error: {job.error_summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

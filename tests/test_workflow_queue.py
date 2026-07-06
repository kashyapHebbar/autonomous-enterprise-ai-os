from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from aeai_os.runs.repository import InMemoryRunRepository
from aeai_os.workflows.queue import RepositoryWorkflowQueue


def test_repository_queue_concurrent_claims_do_not_duplicate_jobs():
    repository = InMemoryRunRepository()
    queue = RepositoryWorkflowQueue(repository)
    claimed_job_ids: list[str] = []
    lock = Lock()

    for index in range(20):
        run = repository.create_run(f"Analyze procurement batch {index}.")
        queue.enqueue(
            run_id=run.id,
            workflow_name="procurement",
            payload={"batch": index},
        )

    def claim_until_empty(worker_id: str) -> None:
        while True:
            job = queue.claim_next(worker_id=worker_id, workflow_name="procurement")
            if job is None:
                return
            with lock:
                claimed_job_ids.append(job.id)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(claim_until_empty, f"worker-{index}")
            for index in range(5)
        ]
        for future in futures:
            future.result()

    assert len(claimed_job_ids) == 20
    assert len(set(claimed_job_ids)) == 20
    assert queue.claim_next(worker_id="worker-final", workflow_name="procurement") is None

from __future__ import annotations

import time
from concurrent.futures import Future, ThreadPoolExecutor

from backend.config import settings
from backend.retrieval_queue import claim_next_job, complete_job, fail_job, requeue_processing_jobs, update_job
from backend.retrieval_tasks import execute_job


def _run_claimed_job(job: dict) -> None:
    job_id = job["job_id"]

    def _progress(payload: dict) -> None:
        update_job(job_id, status="running", **payload)

    try:
        result = execute_job(job.get("job_type") or "", dict(job.get("payload") or {}), progress_callback=_progress)
        complete_job(job_id, result)
    except Exception as exc:
        fail_job(job_id, str(exc))


def run_worker_forever() -> None:
    requeue_processing_jobs()
    max_workers = max(1, int(settings.retrieval_max_concurrency))
    poll_timeout = max(1, int(round(settings.retrieval_worker_poll_seconds)))
    active_futures: dict[Future, str] = {}

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="retrieval-worker") as executor:
        while True:
            done_futures = [future for future in active_futures if future.done()]
            for future in done_futures:
                active_futures.pop(future, None)
                future.result()

            while len(active_futures) < max_workers:
                job = claim_next_job(timeout=poll_timeout)
                if not job:
                    break
                future = executor.submit(_run_claimed_job, job)
                active_futures[future] = job["job_id"]

            if len(active_futures) >= max_workers:
                time.sleep(0.1)


if __name__ == "__main__":
    run_worker_forever()

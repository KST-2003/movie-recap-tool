"""Hand a job to a worker: Redis + RQ in production, an in-process thread pool for local development."""
import os
from concurrent.futures import ThreadPoolExecutor

from config import QUEUE_MODE, REDIS_URL

_executor = None


def enqueue(job_id: str):
    if QUEUE_MODE == "rq":
        from redis import Redis
        from rq import Queue
        Queue("recap", connection=Redis.from_url(REDIS_URL)).enqueue(
            "pipeline.run_job_by_id", job_id, job_timeout=3600, result_ttl=0, failure_ttl=86400)
        return
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=int(os.getenv("RECAP_WORKERS", "2")))
    import pipeline  # heavy imports only when running jobs in-process
    _executor.submit(pipeline.run_job_by_id, job_id)

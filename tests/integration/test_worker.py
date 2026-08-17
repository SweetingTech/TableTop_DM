from __future__ import annotations

import uuid

import pytest
from redis import Redis
from rq import Queue, Retry, SimpleWorker
from rq.job import JobStatus

from tests.integration.worker_tasks import fail_once

pytestmark = pytest.mark.integration


def test_experiment_worker_retries_transient_failure(integration_stack) -> None:
    connection = Redis.from_url(integration_stack.redis_url)
    connection.flushdb()
    queue = Queue("experiments", connection=connection)
    attempt_key = f"test:worker-attempt:{uuid.uuid4()}"
    job = queue.enqueue(
        fail_once,
        integration_stack.redis_url,
        attempt_key,
        retry=Retry(max=1, interval=0),
        job_timeout=30,
    )

    worker = SimpleWorker([queue], connection=connection, name=f"test-worker-{uuid.uuid4()}")
    worker.work(burst=True, with_scheduler=True, logging_level="WARNING")
    job.refresh()

    assert job.get_status(refresh=True) == JobStatus.FINISHED
    assert job.result == 2
    assert int(connection.get(attempt_key)) == 2

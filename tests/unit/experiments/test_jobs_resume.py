from __future__ import annotations

import threading

import pytest

from experiments.jobs import JobManager

pytestmark = pytest.mark.unit


def test_resumable_job_retains_checkpoint_across_failure_and_retry():
    jobs = JobManager()

    def runner(context):
        if context.attempt == 1:
            context.checkpoint({"next_trial": 12}, 0.4)
            raise RuntimeError("worker lost")
        return {"resumed_from": context.checkpoint_data["next_trial"]}

    queued = jobs.create_resumable("scenario", {"seed": 2}, runner)
    failed = jobs.run(queued.job_id)
    finished = jobs.resume(queued.job_id)

    assert failed.status == "FAILED"
    assert failed.checkpoint == {"next_trial": 12}
    assert finished.status == "COMPLETED"
    assert finished.attempt == 2
    assert finished.result == {"resumed_from": 12}


def test_running_job_observes_cooperative_cancellation():
    jobs = JobManager()
    started = threading.Event()
    release = threading.Event()

    def runner(context):
        started.set()
        assert release.wait(timeout=2)
        context.raise_if_cancelled()
        return {"unexpected": True}

    queued = jobs.create_resumable("long", {}, runner)
    worker = threading.Thread(target=jobs.run, args=(queued.job_id,))
    worker.start()
    assert started.wait(timeout=2)
    jobs.cancel(queued.job_id)
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert jobs.get(queued.job_id).status == "CANCELLED"
    assert jobs.get(queued.job_id).result is None


def test_retry_limit_is_enforced_without_losing_checkpoint():
    jobs = JobManager()

    def always_fails(context):
        context.checkpoint({"attempt": context.attempt}, 0.5)
        raise RuntimeError("no")

    queued = jobs.create_resumable("limited", {}, always_fails, max_attempts=2)
    jobs.run(queued.job_id)
    jobs.resume(queued.job_id)
    with pytest.raises(ValueError, match="retry limit"):
        jobs.retry(queued.job_id)
    assert jobs.get(queued.job_id).checkpoint == {"attempt": 2}


def test_job_records_isolate_mutable_requests_from_callers():
    jobs = JobManager()
    request = {"nested": {"seed": 3}}
    queued = jobs.create("copy", request, lambda value: value)

    request["nested"]["seed"] = 99
    queued.request["nested"]["seed"] = 100

    assert jobs.get(queued.job_id).request == {"nested": {"seed": 3}}
    assert jobs.run(queued.job_id).result == {"nested": {"seed": 3}}

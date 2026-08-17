from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from experiments.models import JobRecord
from experiments.onboarding import OnboardingExperiment

JobRunner = Callable[[dict[str, Any]], dict[str, Any]]
ResumableJobRunner = Callable[["JobContext"], dict[str, Any]]


class JobCancelled(RuntimeError):
    pass


class JobContext:
    def __init__(self, manager: JobManager, job_id: uuid.UUID) -> None:
        self._manager = manager
        self.job_id = job_id

    @property
    def request(self) -> dict[str, Any]:
        return copy.deepcopy(self._manager.get(self.job_id).request)

    @property
    def checkpoint_data(self) -> dict[str, Any]:
        return copy.deepcopy(self._manager.get(self.job_id).checkpoint)

    @property
    def attempt(self) -> int:
        return self._manager.get(self.job_id).attempt

    def checkpoint(self, value: dict[str, Any], progress: float) -> JobRecord:
        return self._manager.checkpoint(self.job_id, value, progress)

    def is_cancelled(self) -> bool:
        record = self._manager.get(self.job_id)
        return record.cancellation_requested or record.status == "CANCELLED"

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise JobCancelled("job cancellation requested")


class JobManager:
    """Thread-safe resumable lifecycle shared by local and queued runner adapters."""

    def __init__(self) -> None:
        self._records: dict[uuid.UUID, JobRecord] = {}
        self._runners: dict[uuid.UUID, ResumableJobRunner] = {}
        self._lock = threading.RLock()

    def create(
        self,
        job_type: str,
        request: dict[str, Any],
        runner: JobRunner,
        *,
        max_attempts: int = 3,
    ) -> JobRecord:
        return self.create_resumable(
            job_type,
            request,
            lambda context: runner(context.request),
            max_attempts=max_attempts,
        )

    def create_resumable(
        self,
        job_type: str,
        request: dict[str, Any],
        runner: ResumableJobRunner,
        *,
        max_attempts: int = 3,
    ) -> JobRecord:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        job_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            json.dumps(
                {"type": job_type, "request": request},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ),
        )
        with self._lock:
            existing = self._records.get(job_id)
            if existing is not None:
                self._runners[job_id] = runner
                return existing.model_copy(deep=True)
            record = JobRecord(
                job_id=job_id,
                job_type=job_type,
                status="QUEUED",
                progress=0,
                request=copy.deepcopy(request),
                max_attempts=max_attempts,
            )
            self._records[job_id] = record
            self._runners[job_id] = runner
            return record.model_copy(deep=True)

    def restore(
        self,
        record: JobRecord,
        runner: ResumableJobRunner | None = None,
    ) -> JobRecord:
        """Restore durable job history without silently restarting work.

        A process that disappeared while a local job was RUNNING cannot know
        whether the runner reached an external side effect.  Such records are
        therefore restored as FAILED and require the explicit retry endpoint.
        Terminal records remain inspectable after an API restart.
        """
        restored = record
        if record.status == "RUNNING":
            restored = record.model_copy(
                update={
                    "status": "FAILED",
                    "error": "worker process stopped before recording completion",
                }
            )
        with self._lock:
            existing = self._records.get(restored.job_id)
            if existing is not None and existing != restored:
                raise ValueError("restored job differs from existing job history")
            self._records[restored.job_id] = restored.model_copy(deep=True)
            if runner is not None:
                self._runners[restored.job_id] = runner
        return restored.model_copy(deep=True)

    def attach_runner(self, job_id: uuid.UUID, runner: ResumableJobRunner) -> None:
        """Attach an executable implementation to a rehydrated job record."""
        with self._lock:
            if job_id not in self._records:
                raise KeyError(job_id)
            self._runners[job_id] = runner

    def run(self, job_id: uuid.UUID) -> JobRecord:
        with self._lock:
            record = self._records[job_id]
            if record.status in {"CANCELLED", "COMPLETED", "FAILED"}:
                return record.model_copy(deep=True)
            if record.status == "RUNNING":
                raise ValueError("job is already running")
            record = record.model_copy(
                update={
                    "status": "RUNNING",
                    "progress": max(0.01, record.progress),
                    "cancellation_requested": False,
                }
            )
            self._records[job_id] = record
            try:
                runner = self._runners[job_id]
            except KeyError as exc:
                raise ValueError("job runner is unavailable after restart") from exc
        try:
            result = runner(JobContext(self, job_id))
            with self._lock:
                current = self._records[job_id]
                if current.cancellation_requested or current.status == "CANCELLED":
                    finished = current.model_copy(update={"status": "CANCELLED", "result": None})
                else:
                    finished = current.model_copy(
                        update={
                            "status": "COMPLETED",
                            "progress": 1.0,
                            "result": copy.deepcopy(result),
                        }
                    )
        except JobCancelled:
            with self._lock:
                current = self._records[job_id]
                finished = current.model_copy(update={"status": "CANCELLED"})
        except Exception as exc:  # noqa: BLE001 - job boundary records runner failures
            with self._lock:
                current = self._records[job_id]
                finished = current.model_copy(update={"status": "FAILED", "error": str(exc)})
        with self._lock:
            self._records[job_id] = finished
        return finished.model_copy(deep=True)

    def checkpoint(self, job_id: uuid.UUID, value: dict[str, Any], progress: float) -> JobRecord:
        if not 0 <= progress < 1:
            raise ValueError("checkpoint progress must be in [0, 1)")
        with self._lock:
            record = self._records[job_id]
            if record.status != "RUNNING":
                raise ValueError("only running jobs can checkpoint")
            updated = record.model_copy(
                update={"checkpoint": copy.deepcopy(value), "progress": progress}
            )
            self._records[job_id] = updated
            return updated.model_copy(deep=True)

    def get(self, job_id: uuid.UUID) -> JobRecord:
        with self._lock:
            return self._records[job_id].model_copy(deep=True)

    def list(self) -> tuple[JobRecord, ...]:
        with self._lock:
            return tuple(
                self._records[key].model_copy(deep=True) for key in sorted(self._records, key=str)
            )

    def cancel(self, job_id: uuid.UUID) -> JobRecord:
        with self._lock:
            record = self._records[job_id]
            if record.status in {"COMPLETED", "FAILED"}:
                raise ValueError("terminal jobs cannot be cancelled")
            cancelled = record.model_copy(
                update={
                    "status": "CANCELLED",
                    "cancellation_requested": True,
                }
            )
            self._records[job_id] = cancelled
            return cancelled.model_copy(deep=True)

    def retry(self, job_id: uuid.UUID) -> JobRecord:
        with self._lock:
            record = self._records[job_id]
            if record.status not in {"FAILED", "CANCELLED"}:
                raise ValueError("only failed or cancelled jobs can be retried")
            if record.attempt >= record.max_attempts:
                raise ValueError("job retry limit reached")
            queued = record.model_copy(
                update={
                    "status": "QUEUED",
                    "result": None,
                    "error": None,
                    "attempt": record.attempt + 1,
                    "cancellation_requested": False,
                }
            )
            self._records[job_id] = queued
            return queued.model_copy(deep=True)

    def resume(self, job_id: uuid.UUID) -> JobRecord:
        record = self.get(job_id)
        if record.status in {"FAILED", "CANCELLED"}:
            self.retry(job_id)
        elif record.status != "QUEUED":
            raise ValueError("only queued, failed, or cancelled jobs can resume")
        return self.run(job_id)


def run_onboarding_job(
    output_path: str,
    cohort_size: int,
    seeds: tuple[int, ...],
) -> dict[str, Any]:
    """RQ-compatible job that atomically publishes a normalized report artifact."""
    report = OnboardingExperiment().run_cohort(cohort_size=cohort_size, seeds=seeds)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, destination)
    return {
        "scenario_id": report.scenario_id,
        "trial_count": report.trial_count,
        "artifact": str(destination),
        "canonical_world_unchanged": report.canonical_world_unchanged,
    }

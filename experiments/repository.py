from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import psycopg2.extras

from experiments.history import ExperimentHistoryStore
from experiments.models import (
    CohortReport,
    JobRecord,
    ScenarioDefinition,
    TrialOutput,
    TrialRecord,
)
from kernel.database import execute_one, transaction


def _scenario_uuid(scenario_id: str, version: str) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tabletop-dm:scenario:{scenario_id}:{version}",
    )


class InMemoryExperimentRepository:
    """Deterministic lifecycle adapter for tests and local ephemeral runs."""

    def __init__(self) -> None:
        self._scenarios: dict[tuple[str, str], ScenarioDefinition] = {}
        self._trials: dict[uuid.UUID, TrialRecord] = {}
        self._outputs: dict[uuid.UUID, TrialOutput] = {}

    def save_scenario(self, definition: ScenarioDefinition) -> uuid.UUID:
        key = (definition.scenario_id, definition.version)
        existing = self._scenarios.get(key)
        if existing is not None and existing != definition:
            raise ValueError("An immutable scenario version cannot be replaced")
        self._scenarios[key] = definition.model_copy(deep=True)
        return _scenario_uuid(*key)

    def get_scenario(self, scenario_id: str, version: str) -> ScenarioDefinition:
        return self._scenarios[(scenario_id, version)].model_copy(deep=True)

    def list_scenarios(self) -> tuple[ScenarioDefinition, ...]:
        return tuple(self._scenarios[key].model_copy(deep=True) for key in sorted(self._scenarios))

    def save_trial(self, record: TrialRecord) -> None:
        existing = self._trials.get(record.trial_id)
        if existing is not None:
            immutable = (
                "scenario_id",
                "scenario_version",
                "persona_id",
                "persona_version",
                "world_id",
                "snapshot_id",
                "branch_id",
                "run_id",
                "seed",
                "attempt",
            )
            if any(getattr(existing, field) != getattr(record, field) for field in immutable):
                raise ValueError("Trial identity fields cannot change")
        self._trials[record.trial_id] = record.model_copy(deep=True)

    def save_output(self, record: TrialRecord, output: TrialOutput) -> None:
        if record.trial_id != output.trial_id:
            raise ValueError("Trial record and output IDs differ")
        self.save_trial(record)
        existing = self._outputs.get(output.trial_id)
        if existing is not None and existing != output:
            raise ValueError("A normalized trial output cannot be replaced")
        self._outputs[output.trial_id] = output.model_copy(deep=True)

    def trial(self, trial_id: uuid.UUID) -> TrialRecord:
        return self._trials[trial_id].model_copy(deep=True)

    def output(self, trial_id: uuid.UUID) -> TrialOutput:
        return self._outputs[trial_id].model_copy(deep=True)

    def trials(self) -> tuple[TrialRecord, ...]:
        return tuple(
            self._trials[key].model_copy(deep=True) for key in sorted(self._trials, key=str)
        )


class PostgresExperimentRepository:
    """Adapter for the experiments tables in the v2 baseline migration."""

    def __init__(
        self,
        dsn: str | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        self.dsn = dsn
        self.history = ExperimentHistoryStore(artifact_root) if artifact_root else None

    def save_scenario(self, definition: ScenarioDefinition) -> uuid.UUID:
        scenario_uuid = _scenario_uuid(definition.scenario_id, definition.version)
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO experiments.scenarios (
                      id, scenario_key, version, definition, metric_contract
                    ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (scenario_key, version) DO NOTHING
                    """,
                    (
                        str(scenario_uuid),
                        definition.scenario_id,
                        definition.version,
                        definition.model_dump_json(),
                        json.dumps(definition.metric_contract, sort_keys=True),
                    ),
                )
        stored = self.get_scenario(definition.scenario_id, definition.version)
        if stored != definition:
            raise ValueError("Stored scenario version differs from immutable definition")
        return scenario_uuid

    def get_scenario(self, scenario_id: str, version: str) -> ScenarioDefinition:
        row = execute_one(
            """
            SELECT definition
            FROM experiments.scenarios
            WHERE scenario_key = %s AND version = %s
            """,
            (scenario_id, version),
            dsn=self.dsn,
        )
        if row is None:
            raise KeyError(f"Unknown scenario {scenario_id}@{version}")
        return ScenarioDefinition.model_validate(row["definition"])

    def list_scenarios(self) -> tuple[ScenarioDefinition, ...]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT definition FROM experiments.scenarios
                    ORDER BY scenario_key, version
                    """
                )
                rows = cursor.fetchall()
        return tuple(ScenarioDefinition.model_validate(row["definition"]) for row in rows)

    def save_trial(self, record: TrialRecord) -> None:
        scenario_uuid = _scenario_uuid(record.scenario_id, record.scenario_version)
        terminal = record.status in {"COMPLETED", "FAILED", "CANCELLED"}
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO experiments.trials (
                      id, scenario_id, persona_id, persona_version_id, world_id,
                      snapshot_id, branch_id, run_id, seed, status, attempt,
                      failure_code, started_at, completed_at
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                      CASE WHEN %s = 'RUNNING' THEN now() ELSE NULL END,
                      CASE WHEN %s THEN now() ELSE NULL END
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      status = EXCLUDED.status,
                      failure_code = EXCLUDED.failure_code,
                      started_at = COALESCE(experiments.trials.started_at, EXCLUDED.started_at),
                      completed_at = EXCLUDED.completed_at
                    """,
                    (
                        str(record.trial_id),
                        str(scenario_uuid),
                        str(record.persona_id) if record.persona_id else None,
                        record.persona_version,
                        str(record.world_id),
                        str(record.snapshot_id),
                        str(record.branch_id),
                        str(record.run_id),
                        record.seed,
                        record.status,
                        record.attempt,
                        record.failure_code,
                        record.status,
                        terminal,
                    ),
                )

    def save_output(self, record: TrialRecord, output: TrialOutput) -> None:
        self.save_trial(record)
        artifact: tuple[Path, str] | None = None
        if self.history is not None:
            path = self.history.save_trial(output)
            artifact = (path, hashlib.sha256(path.read_bytes()).hexdigest())
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                if artifact is not None:
                    _artifact_id, inserted = self._insert_artifact(
                        cursor,
                        kind="experiment-trial-output",
                        path=artifact[0],
                        content_hash=artifact[1],
                        metadata={"trial_output": output.model_dump(mode="json")},
                        world_id=record.world_id,
                        branch_id=record.branch_id,
                    )
                    if not inserted:
                        return
                for fact in output.facts:
                    cursor.execute(
                        """
                        INSERT INTO experiments.verifier_facts (
                          trial_id, fact_type, value, unit,
                          evidence_event_ids, verifier_version
                        ) VALUES (%s,%s,%s::jsonb,%s,%s::uuid[],%s)
                        """,
                        (
                            str(output.trial_id),
                            fact.fact_type,
                            json.dumps(fact.value, default=str),
                            fact.unit,
                            [str(value) for value in fact.evidence_event_ids],
                            fact.verifier_version,
                        ),
                    )
                for name, value in sorted(output.metrics.items()):
                    if not isinstance(value, (bool, int, float)):
                        continue
                    cursor.execute(
                        """
                        INSERT INTO experiments.metrics (
                          trial_id, metric_name, metric_value,
                          metric_version, dimensions
                        ) VALUES (%s,%s,%s,%s,'{}'::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            str(output.trial_id),
                            name,
                            float(value),
                            "1.0.0",
                        ),
                    )

    def save_trial_artifact(self, output: TrialOutput) -> uuid.UUID | None:
        """Catalog outputs such as onboarding fixtures that lack durable branch FKs."""
        if self.history is None:
            return None
        path = self.history.save_trial(output)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                artifact_id, _inserted = self._insert_artifact(
                    cursor,
                    kind="experiment-trial-output",
                    path=path,
                    content_hash=content_hash,
                    metadata={"trial_output": output.model_dump(mode="json")},
                )
        return artifact_id

    def save_report(self, report_id: uuid.UUID, report: CohortReport) -> uuid.UUID | None:
        if self.history is None:
            return None
        path = self.history.save_report(report_id, report)
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                artifact_id, _inserted = self._insert_artifact(
                    cursor,
                    kind="experiment-cohort-report",
                    path=path,
                    content_hash=content_hash,
                    metadata={
                        "report_id": str(report_id),
                        "report": report.model_dump(mode="json"),
                    },
                )
        return artifact_id

    def save_job(
        self,
        record: JobRecord,
        *,
        result_artifact_id: uuid.UUID | None = None,
    ) -> None:
        terminal = record.status in {"COMPLETED", "FAILED", "CANCELLED"}
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO experiments.jobs (
                      id, job_kind, queue_name, status, parameters, attempts,
                      max_attempts, result_artifact_id, last_error,
                      started_at, completed_at
                    ) VALUES (
                      %s,%s,'experiments',%s,%s::jsonb,%s,%s,%s,%s,
                      CASE WHEN %s IN ('RUNNING','COMPLETED','FAILED','CANCELLED')
                           THEN now() ELSE NULL END,
                      CASE WHEN %s THEN now() ELSE NULL END
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      status = EXCLUDED.status,
                      parameters = EXCLUDED.parameters,
                      attempts = EXCLUDED.attempts,
                      max_attempts = EXCLUDED.max_attempts,
                      result_artifact_id = COALESCE(
                        EXCLUDED.result_artifact_id, experiments.jobs.result_artifact_id
                      ),
                      last_error = EXCLUDED.last_error,
                      started_at = COALESCE(experiments.jobs.started_at, EXCLUDED.started_at),
                      completed_at = EXCLUDED.completed_at
                    """,
                    (
                        str(record.job_id),
                        record.job_type,
                        record.status,
                        json.dumps(
                            {"job_record": record.model_dump(mode="json")},
                            default=str,
                        ),
                        record.attempt,
                        record.max_attempts,
                        str(result_artifact_id) if result_artifact_id else None,
                        record.error,
                        record.status,
                        terminal,
                    ),
                )

    def load_jobs(self) -> tuple[JobRecord, ...]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT parameters FROM experiments.jobs
                    ORDER BY created_at, id
                    """
                )
                rows = cursor.fetchall()
        return tuple(
            JobRecord.model_validate(row["parameters"]["job_record"])
            for row in rows
            if "job_record" in row["parameters"]
        )

    def load_reports(self) -> tuple[tuple[uuid.UUID, CohortReport], ...]:
        records: list[tuple[uuid.UUID, CohortReport]] = []
        for metadata in self._artifact_metadata("experiment-cohort-report"):
            if "report_id" in metadata and "report" in metadata:
                records.append(
                    (
                        uuid.UUID(str(metadata["report_id"])),
                        CohortReport.model_validate(metadata["report"]),
                    )
                )
        return tuple(records)

    def load_trial_outputs(self) -> tuple[TrialOutput, ...]:
        return tuple(
            TrialOutput.model_validate(metadata["trial_output"])
            for metadata in self._artifact_metadata("experiment-trial-output")
            if "trial_output" in metadata
        )

    def _artifact_metadata(self, kind: str) -> tuple[dict[str, Any], ...]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT metadata FROM artifacts.objects
                    WHERE artifact_kind = %s
                    ORDER BY created_at, id
                    """,
                    (kind,),
                )
                rows = cursor.fetchall()
        return tuple(dict(row["metadata"]) for row in rows)

    @staticmethod
    def _insert_artifact(
        cursor: Any,
        *,
        kind: str,
        path: Path,
        content_hash: str,
        metadata: dict[str, Any],
        world_id: uuid.UUID | None = None,
        branch_id: uuid.UUID | None = None,
    ) -> tuple[uuid.UUID, bool]:
        artifact_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:artifact:{world_id}:{kind}:{content_hash}",
        )
        cursor.execute(
            """
            INSERT INTO artifacts.objects (
              id, world_id, branch_id, artifact_kind, uri, content_hash,
              media_type, byte_size, metadata
            ) VALUES (%s,%s,%s,%s,%s,%s,'application/json',%s,%s::jsonb)
            ON CONFLICT (world_id, artifact_kind, content_hash) DO NOTHING
            RETURNING id
            """,
            (
                str(artifact_id),
                str(world_id) if world_id else None,
                str(branch_id) if branch_id else None,
                kind,
                path.resolve().as_uri(),
                content_hash,
                path.stat().st_size,
                json.dumps(metadata, default=str),
            ),
        )
        inserted = cursor.fetchone()
        if inserted is not None:
            return uuid.UUID(str(inserted[0])), True
        cursor.execute(
            """
            SELECT id FROM artifacts.objects
            WHERE world_id IS NOT DISTINCT FROM %s
              AND artifact_kind = %s AND content_hash = %s
            """,
            (str(world_id) if world_id else None, kind, content_hash),
        )
        existing = cursor.fetchone()
        if existing is None:
            raise RuntimeError("artifact catalog conflict could not be resolved")
        return uuid.UUID(str(existing[0])), False

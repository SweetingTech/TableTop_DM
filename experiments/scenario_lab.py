from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable

from experiments.artifacts import LocalArtifactStore
from experiments.models import CohortReport, ScenarioDefinition, ScenarioRecord

ScenarioExecutor = Callable[[ScenarioDefinition], CohortReport]


class ScenarioLab:
    """Immutable version registry with archival and snapshot-isolation enforcement."""

    def __init__(self, artifacts: LocalArtifactStore | None = None) -> None:
        self._records: dict[tuple[str, str], ScenarioRecord] = {}
        self._executors: dict[tuple[str, str], ScenarioExecutor] = {}
        self._reports: dict[uuid.UUID, CohortReport] = {}
        self._report_scenarios: dict[uuid.UUID, tuple[str, str]] = {}
        self.artifacts = artifacts

    def create(
        self,
        definition: ScenarioDefinition,
        executor: ScenarioExecutor | None = None,
        *,
        predecessor_version: str | None = None,
    ) -> ScenarioRecord:
        key = (definition.scenario_id, definition.version)
        if key in self._records:
            raise ValueError(f"Scenario already registered: {key}")
        if predecessor_version is not None:
            predecessor = (definition.scenario_id, predecessor_version)
            if predecessor not in self._records:
                raise KeyError(f"Unknown predecessor scenario {predecessor}")
        stored_definition = definition.model_copy(deep=True)
        encoded = json.dumps(
            stored_definition.model_dump(mode="json", exclude_none=False),
            sort_keys=True,
            separators=(",", ":"),
        )
        record = ScenarioRecord(
            definition=stored_definition,
            content_hash=hashlib.sha256(encoded.encode()).hexdigest(),
            predecessor_version=predecessor_version,
        )
        self._records[key] = record
        if executor is not None:
            self._executors[key] = executor
        return record.model_copy(deep=True)

    def register(self, definition: ScenarioDefinition, executor: ScenarioExecutor) -> None:
        self.create(definition, executor)

    def update(
        self,
        scenario_id: str,
        predecessor_version: str,
        definition: ScenarioDefinition,
        executor: ScenarioExecutor | None = None,
    ) -> ScenarioRecord:
        if definition.scenario_id != scenario_id:
            raise ValueError("A scenario version cannot change scenario_id")
        return self.create(
            definition,
            executor,
            predecessor_version=predecessor_version,
        )

    def get(self, scenario_id: str, version: str) -> ScenarioRecord:
        return self._records[(scenario_id, version)].model_copy(deep=True)

    def archive(self, scenario_id: str, version: str) -> ScenarioRecord:
        key = (scenario_id, version)
        record = self._records[key]
        if record.status == "ARCHIVED":
            return record.model_copy(deep=True)
        archived = record.model_copy(update={"status": "ARCHIVED"})
        self._records[key] = archived
        return archived.model_copy(deep=True)

    def delete(self, scenario_id: str, version: str) -> ScenarioRecord:
        """Delete is a tombstone operation; immutable definitions remain inspectable."""
        return self.archive(scenario_id, version)

    def definitions(self, *, include_archived: bool = False) -> tuple[ScenarioDefinition, ...]:
        return tuple(
            record.definition.model_copy(deep=True)
            for key in sorted(self._records)
            for record in (self._records[key],)
            if include_archived or record.status == "ACTIVE"
        )

    def run(self, scenario_id: str, version: str) -> tuple[uuid.UUID, CohortReport]:
        key = (scenario_id, version)
        record = self._records.get(key)
        if record is None:
            raise KeyError(f"Unknown scenario {scenario_id}@{version}")
        if record.status != "ACTIVE":
            raise ValueError("Archived scenarios cannot start new runs")
        if key not in self._executors:
            raise ValueError(f"Scenario {scenario_id}@{version} has no executor")
        report = self._executors[key](record.definition.model_copy(deep=True))
        if (report.scenario_id, report.scenario_version) != key:
            raise ValueError("Scenario executor returned a report for another version")
        if not report.canonical_world_unchanged:
            raise RuntimeError("Trial executor violated canonical branch isolation")
        report_identity = json.dumps(
            report.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        report_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:report:{scenario_id}:{version}:{report_identity}",
        )
        stored_report = report.model_copy(deep=True)
        self._reports[report_id] = stored_report
        self._report_scenarios[report_id] = key
        if self.artifacts is not None:
            self.artifacts.write_json(
                "cohort-report",
                str(report_id),
                stored_report.model_dump(mode="json"),
            )
        return report_id, stored_report.model_copy(deep=True)

    def report(self, report_id: uuid.UUID) -> CohortReport:
        return self._reports[report_id].model_copy(deep=True)

    def reports_for(
        self, scenario_id: str, version: str | None = None
    ) -> tuple[tuple[uuid.UUID, CohortReport], ...]:
        return tuple(
            (report_id, self._reports[report_id].model_copy(deep=True))
            for report_id in sorted(self._reports, key=str)
            if self._report_scenarios[report_id][0] == scenario_id
            and (version is None or self._report_scenarios[report_id][1] == version)
        )

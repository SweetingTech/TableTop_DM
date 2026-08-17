from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from experiments.models import CohortReport, JobRecord, ScenarioDefinition, TrialOutput


class ExperimentHistoryStore:
    """Filesystem-backed API history with immutable reports and trial outputs.

    PostgreSQL catalogs these files in durable deployments, while this store also
    gives local-reference mode useful restart behavior. Job lifecycle documents
    are replaceable projections; normalized reports and trial outputs are not.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def save_trial(self, output: TrialOutput) -> Path:
        return self._write_immutable(
            self.root / "trials" / f"{output.trial_id}.json",
            output.model_dump(mode="json"),
        )

    def save_scenario(self, definition: ScenarioDefinition) -> Path:
        identity = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:scenario:{definition.scenario_id}:{definition.version}",
        )
        return self._write_immutable(
            self.root / "scenarios" / f"{identity}.json",
            definition.model_dump(mode="json"),
        )

    def scenarios(self) -> tuple[ScenarioDefinition, ...]:
        return tuple(
            ScenarioDefinition.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self._paths("scenarios")
        )

    def trials(self) -> tuple[TrialOutput, ...]:
        return tuple(
            TrialOutput.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self._paths("trials")
        )

    def trial_path(self, trial_id: uuid.UUID) -> Path:
        return self.root / "trials" / f"{trial_id}.json"

    def save_report(self, report_id: uuid.UUID, report: CohortReport) -> Path:
        payload = {
            "report_id": str(report_id),
            "report": report.model_dump(mode="json"),
        }
        return self._write_immutable(
            self.root / "reports" / f"{report_id}.json",
            payload,
        )

    def reports(self) -> tuple[tuple[uuid.UUID, CohortReport], ...]:
        records: list[tuple[uuid.UUID, CohortReport]] = []
        for path in self._paths("reports"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            records.append(
                (
                    uuid.UUID(str(payload["report_id"])),
                    CohortReport.model_validate(payload["report"]),
                )
            )
        return tuple(records)

    def report_path(self, report_id: uuid.UUID) -> Path:
        return self.root / "reports" / f"{report_id}.json"

    def save_job(self, record: JobRecord) -> Path:
        destination = self.root / "jobs" / f"{record.job_id}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, destination)
        return destination

    def jobs(self) -> tuple[JobRecord, ...]:
        return tuple(
            JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in self._paths("jobs")
        )

    def _paths(self, name: str) -> tuple[Path, ...]:
        directory = self.root / name
        if not directory.exists():
            return ()
        return tuple(sorted(directory.glob("*.json"), key=lambda path: path.name))

    @staticmethod
    def _write_immutable(destination: Path, payload: dict) -> Path:
        encoded = json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        )
        if destination.exists():
            if destination.read_text(encoding="utf-8") != encoded:
                raise ValueError(f"Immutable experiment artifact differs: {destination.name}")
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        os.replace(temporary, destination)
        return destination

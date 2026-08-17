from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

import experiments.repository as repository_module
from experiments.models import TrialRecord
from experiments.repository import PostgresExperimentRepository

pytestmark = pytest.mark.unit


def test_postgres_trial_adapter_targets_baseline_persona_version_id(monkeypatch):
    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.cursor.return_value = cursor_context

    @contextmanager
    def fake_transaction(*, dsn=None):
        yield connection

    monkeypatch.setattr(repository_module, "transaction", fake_transaction)
    record = TrialRecord(
        trial_id=uuid.UUID(int=4100),
        scenario_id="opening",
        scenario_version="1",
        persona_id=uuid.UUID(int=4101),
        persona_version=str(uuid.UUID(int=4102)),
        world_id=uuid.UUID(int=4103),
        snapshot_id=uuid.UUID(int=4104),
        branch_id=uuid.UUID(int=4105),
        run_id=uuid.UUID(int=4106),
        seed=7,
        status="RUNNING",
    )

    PostgresExperimentRepository("postgresql://unused").save_trial(record)

    statement = cursor.execute.call_args.args[0]
    assert "persona_version_id" in statement
    assert "persona_version," not in statement

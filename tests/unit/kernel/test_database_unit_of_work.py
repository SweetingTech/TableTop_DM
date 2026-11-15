from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from kernel.database import after_commit, transaction, unit_of_work

pytestmark = pytest.mark.unit


def test_composed_repositories_commit_once_and_publish_only_after_commit(monkeypatch):
    connection = MagicMock()
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr("kernel.database.psycopg2.connect", connect)
    actor = uuid.uuid4()
    published = []
    with unit_of_work(actor_id=actor, dsn="test-dsn") as outer:
        with transaction(actor_id=actor, dsn="test-dsn") as inner:
            assert inner is outer
            assert after_commit(lambda: published.append(connection.commit.call_count))
        with transaction(dsn="test-dsn") as portal:
            assert portal is outer
        assert not published
    assert published == [1]
    assert connect.call_count == 1 and connection.commit.call_count == 1
    assert connection.rollback.call_count == 0 and connection.close.call_count == 1
    assert not after_commit(lambda: published.append(2))


@pytest.mark.parametrize("failure", ["actor", "database", "caught"])
def test_scope_switch_and_caught_failure_roll_back_entire_unit(monkeypatch, failure):
    connection = MagicMock()
    monkeypatch.setattr("kernel.database.psycopg2.connect", MagicMock(return_value=connection))
    actor = uuid.uuid4()
    published = []
    with pytest.raises(RuntimeError, match="rolled back"):
        with unit_of_work(actor_id=actor, dsn="test-dsn"):
            assert after_commit(lambda: published.append(True))
            try:
                with transaction(
                    actor_id=uuid.uuid4() if failure == "actor" else actor,
                    dsn="other-dsn" if failure == "database" else "test-dsn",
                ):
                    raise ValueError("nested failure")
            except (ValueError, RuntimeError):
                pass
    assert not published and connection.commit.call_count == 0
    assert connection.rollback.call_count == 1 and connection.close.call_count == 1

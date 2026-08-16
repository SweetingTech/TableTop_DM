import uuid

import pytest

from services.orchestrator.delta_dispatcher import (
    StateDeltaDispatcher,
    UnsupportedStateDeltaError,
)
from shared.schemas.events import StateDelta


class CursorSpy:
    def __init__(self):
        self.calls = []
        self.closed = False

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def close(self):
        self.closed = True


class ConnSpy:
    def __init__(self):
        self.cursor_spy = CursorSpy()

    def cursor(self):
        return self.cursor_spy


def test_dispatcher_applies_entity_hp_and_position_updates():
    entity_id = uuid.uuid4()
    conn = ConnSpy()
    dispatcher = StateDeltaDispatcher()

    dispatcher.apply(
        StateDelta(
            table="state.entities",
            operation="UPDATE",
            entity_id=entity_id,
            changes={"hp_current": 7, "public_sheet_x": 4, "public_sheet_y": 9},
        ),
        conn,
    )

    assert len(conn.cursor_spy.calls) == 2
    assert "hp_current" in conn.cursor_spy.calls[0][0]
    assert conn.cursor_spy.calls[0][1] == (7, str(entity_id))
    assert "jsonb_set" in conn.cursor_spy.calls[1][0]
    assert conn.cursor_spy.calls[1][1] == ("4", "9", str(entity_id))
    assert conn.cursor_spy.closed


def test_dispatcher_applies_condition_insert_and_delete():
    entity_id = uuid.uuid4()
    conn = ConnSpy()
    dispatcher = StateDeltaDispatcher()

    dispatcher.apply(
        StateDelta(
            table="state.conditions",
            operation="INSERT",
            entity_id=entity_id,
            changes={"condition_type": "PRONE", "duration_rounds": 2, "source": "test"},
        ),
        conn,
    )
    dispatcher.apply(
        StateDelta(
            table="state.conditions",
            operation="DELETE",
            entity_id=entity_id,
            changes={"condition_type": "PRONE"},
        ),
        conn,
    )

    assert "INSERT INTO state.conditions" in conn.cursor_spy.calls[0][0]
    assert conn.cursor_spy.calls[0][1] == (
        str(entity_id),
        None,
        "PRONE",
        2,
        "test",
    )
    assert "DELETE FROM state.conditions" in conn.cursor_spy.calls[1][0]
    assert conn.cursor_spy.calls[1][1] == (str(entity_id), "PRONE")


def test_dispatcher_rejects_unknown_delta_operations():
    dispatcher = StateDeltaDispatcher()

    with pytest.raises(UnsupportedStateDeltaError):
        dispatcher.apply(
            StateDelta(table="state.unknown", operation="UPSERT", changes={}),
            ConnSpy(),
        )

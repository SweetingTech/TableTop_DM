"""Unit-test the patcher's dispatch table without touching the DB.

We mock the connection-level helpers and confirm each event_type lands
in the right story_state field. The real DB integration is exercised by
the manual smoke test at app boot.
"""

from unittest.mock import MagicMock
import uuid

import pytest

pytestmark = pytest.mark.unit


def _make_patch(event_type, delta=None, visibility="party", summary="test"):
    return {
        "id": str(uuid.uuid4()),
        "campaign_id": str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "event_type": event_type,
        "summary": summary,
        "patch": delta or {},
        "visibility": visibility,
        "status": "APPROVED",
    }


def test_location_changed_sets_current_location():
    from services.session_intel.patcher import _apply_event

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    p = _make_patch("location_changed", delta={"current_location": "Eclipse Keep"})
    _apply_event(conn, p)
    # The patcher's _set_scalar issues an UPDATE state.story_state SET current_location = ...
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("current_location = %s" in sql for sql in sql_calls)


def test_promise_made_appends_to_plot_threads():
    from services.session_intel.patcher import _apply_event

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = ([],)  # empty existing JSONB list
    conn.cursor.return_value = cur
    p = _make_patch("promise_made", delta={"target": "ghost", "obligation": "burial"})
    _apply_event(conn, p)
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("plot_threads" in sql for sql in sql_calls)


def test_retcon_writes_to_dm_notes():
    from services.session_intel.patcher import _apply_event

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    p = _make_patch(
        "retcon_or_contradiction",
        summary="player said Joran died, but ledger has him alive",
    )
    _apply_event(conn, p)
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("dm_notes" in sql for sql in sql_calls)


def test_unknown_event_type_falls_through_to_dm_notes():
    from services.session_intel.patcher import _apply_event

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    p = _make_patch(
        "entirely_new_event_kind", summary="something the schema didn't anticipate"
    )
    _apply_event(conn, p)
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("dm_notes" in sql for sql in sql_calls)


def test_secret_revealed_routes_by_visibility():
    from services.session_intel.patcher import _apply_event

    # dm_only goes to dm_notes
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    p = _make_patch(
        "secret_revealed", visibility="dm_only", summary="villain's true name"
    )
    _apply_event(conn, p)
    sql_calls = [c.args[0] for c in cur.execute.call_args_list]
    assert any("dm_notes" in sql for sql in sql_calls)

    # public goes to recent_events (JSONB list)
    conn2 = MagicMock()
    cur2 = MagicMock()
    cur2.fetchone.return_value = ([],)
    conn2.cursor.return_value = cur2
    p2 = _make_patch("secret_revealed", visibility="public", summary="ally was a spy")
    _apply_event(conn2, p2)
    sql_calls2 = [c.args[0] for c in cur2.execute.call_args_list]
    assert any("recent_events" in sql for sql in sql_calls2)

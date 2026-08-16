import pytest

from services.saves.game_save import (
    _complete_principal_remap,
    _insert_row,
    _referenced_principal_ids,
)


class RecordingCursor:
    def __init__(self, rows=None):
        self.sql = None
        self.params = None
        self.rows = rows or []

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def close(self):
        pass

    def fetchall(self):
        return self.rows


class RecordingConnection:
    def __init__(self, rows=None):
        self.cursor_instance = RecordingCursor(rows)

    def cursor(self):
        return self.cursor_instance


def test_insert_row_remaps_ledger_sender_and_visibility_audience():
    source_player = "22222222-2222-2222-2222-222222222222"
    source_gm = "22222222-2222-2222-2222-222222222221"
    destination_player = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    destination_gm = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    row = {
        "sender_principal_id": source_player,
        "visible_to": [source_player, source_gm],
        "domain_tags": ["qa"],
        "payload": {"message": "portable"},
    }
    conn = RecordingConnection()

    _insert_row(
        conn,
        "ledger.session_ledger",
        row,
        principal_remap={
            source_player: destination_player,
            source_gm: destination_gm,
        },
        jsonb_cols=("payload",),
        array_cols=("domain_tags", "visible_to"),
    )

    values = dict(zip(row, conn.cursor_instance.params, strict=True))
    assert values["sender_principal_id"] == destination_player
    assert values["visible_to"] == [destination_player, destination_gm]
    assert "%s::uuid[]" in conn.cursor_instance.sql


def test_insert_row_rejects_unmapped_principal_reference():
    conn = RecordingConnection()

    with pytest.raises(ValueError, match="No destination principal mapping"):
        _insert_row(
            conn,
            "ledger.session_ledger",
            {"sender_principal_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc"},
            principal_remap={"unused": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"},
        )


def test_referenced_principals_rejects_string_visibility_array():
    with pytest.raises(ValueError, match="visible_to must be an array"):
        _referenced_principal_ids(
            {
                "ledger_events": [
                    {"visible_to": "{22222222-2222-2222-2222-222222222222}"}
                ]
            }
        )


def test_complete_principal_remap_looks_up_legacy_ids_in_one_query():
    existing_id = "22222222-2222-2222-2222-222222222222"
    unknown_id = "33333333-3333-3333-3333-333333333333"
    conn = RecordingConnection(rows=[(existing_id,)])
    remap = {}
    payload = {
        "ledger_events": [
            {"sender_principal_id": existing_id, "visible_to": [unknown_id]}
        ]
    }

    with pytest.raises(ValueError, match=unknown_id):
        _complete_principal_remap(conn, payload, remap)

    assert "ANY(%s::uuid[])" in conn.cursor_instance.sql
    assert conn.cursor_instance.params == ([existing_id, unknown_id],)
    assert remap == {existing_id: existing_id}

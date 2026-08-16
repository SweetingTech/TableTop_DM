import pytest

from services.saves.game_save import _insert_row, _referenced_principal_ids


class RecordingCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def close(self):
        pass


class RecordingConnection:
    def __init__(self):
        self.cursor_instance = RecordingCursor()

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

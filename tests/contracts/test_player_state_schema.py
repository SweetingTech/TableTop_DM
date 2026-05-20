from shared.schemas.player_state import PlayerStateSnapshot


def test_player_state_snapshot_schema_accepts_contract_shape():
    snapshot = PlayerStateSnapshot.model_validate(
        {
            "campaign_id": "11111111-1111-1111-1111-111111111111",
            "session_id": "66666666-6666-6666-6666-666666666661",
            "snapshot_version": 1,
            "generated_at": "2026-05-17T20:00:00Z",
            "principal": {
                "principal_id": "22222222-2222-2222-2222-222222222222",
                "role": "PLAYER",
                "permissions": ["read_visible_state"],
            },
            "controlled_entities": [
                {
                    "entity_id": "33333333-3333-3333-3333-333333333331",
                    "name": "Rook",
                    "kind": "PC",
                    "current_map_id": None,
                    "position": {"x": 1, "y": 2},
                    "stats": {},
                    "resources": {},
                    "conditions": [],
                    "inventory": [],
                    "public_sheet": {},
                    "private_sheet": {},
                    "death_state": "ACTIVE",
                    "can_command": True,
                }
            ],
            "visible_world": {
                "current_maps": [],
                "visible_entities": [],
                "visible_pois": [],
                "visible_decorations": [],
                "visible_recent_events": [],
                "event_cursor": {"last_ledger_id": None, "last_sequence": None},
            },
            "turn_state": {
                "mode": "EXPLORATION",
                "encounter_id": None,
                "round": None,
                "active_entity_id": None,
                "is_my_turn": False,
                "legal_actions": [
                    {"action": "move", "enabled": True, "requires_target": False}
                ],
            },
            "narrative_state": {},
            "ui_state": {
                "selected_entity_id": "33333333-3333-3333-3333-333333333331",
                "command_locked": False,
                "reconnect_required": False,
            },
        }
    )

    assert snapshot.snapshot_version == 1
    assert snapshot.turn_state.legal_actions[0].action == "move"

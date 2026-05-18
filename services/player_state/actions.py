from __future__ import annotations

from shared.schemas.player_state import LegalAction


def _action(action: str, enabled: bool, reason: str | None = None, *, requires_target: bool = False) -> LegalAction:
    return LegalAction(action=action, enabled=enabled, reason=reason, requires_target=requires_target)


def legal_actions_for(
    *,
    mode: str,
    session_status: str,
    controlled_entities: list[dict],
    visible_entities: list[dict],
    encounter: dict | None,
    active_slot: dict | None,
) -> list[LegalAction]:
    if session_status != "ACTIVE":
        return [
            _action("move", False, "Session is not active."),
            _action("talk", False, "Session is not active.", requires_target=True),
            _action("attack", False, "Session is not active.", requires_target=True),
            _action("end_turn", False, "Session is not active."),
        ]

    if not controlled_entities:
        return [
            _action("move", False, "No controlled active character in this session."),
            _action("talk", False, "No controlled active character in this session.", requires_target=True),
            _action("attack", False, "No controlled active character in this session.", requires_target=True),
            _action("end_turn", False, "No controlled active character in this session."),
        ]

    active_entity_id = str(active_slot["entity_id"]) if active_slot else None
    controlled_ids = {str(e["id"]) for e in controlled_entities}
    is_my_turn = bool(active_entity_id and active_entity_id in controlled_ids)
    visible_targets = [
        e for e in visible_entities
        if str(e.get("id")) not in controlled_ids and e.get("entity_type") in {"NPC", "PC"}
    ]

    actions = [
        _action("move", True),
        _action("talk", bool(visible_targets), None if visible_targets else "No visible target.", requires_target=True),
    ]

    if mode == "COMBAT":
        actions.append(_action(
            "attack",
            is_my_turn and bool(visible_targets),
            None if is_my_turn and visible_targets else (
                "Not currently this entity's turn." if not is_my_turn else "No visible hostile target in range."
            ),
            requires_target=True,
        ))
        actions.append(_action(
            "end_turn",
            is_my_turn,
            None if is_my_turn else "Not currently this entity's turn.",
        ))
    else:
        actions.append(_action("attack", False, "Not in combat.", requires_target=True))
        actions.append(_action("end_turn", False, "Not in combat."))

    return actions

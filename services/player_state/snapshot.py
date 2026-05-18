from __future__ import annotations

from datetime import datetime, timezone
import uuid

from shared.auth.principal import PrincipalContext, load_principal
from shared.db.connection import execute_one, execute_query
from shared.schemas.player_state import (
    ControlledEntitySnapshot,
    EventCursor,
    NarrativeStateSnapshot,
    PlayerStateSnapshot,
    PrincipalSnapshot,
    TurnStateSnapshot,
    UiStateSnapshot,
    VisibleWorldSnapshot,
)
from services.session_intel.continuity import npc_memory, open_threads, unresolved_promises

from .actions import legal_actions_for
from .serializers import row_dict
from .visibility import visible_decorations, visible_entities, visible_pois, visible_recent_events


class PlayerStateError(Exception):
    def __init__(self, code: str, status_code: int):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _permissions(principal: PrincipalContext) -> list[str]:
    perms = ["read_visible_state"]
    if principal.is_gm() or principal.is_system():
        perms.extend(["submit_any_entity_intents", "inspect_player_state"])
    elif principal.controlled_entity_ids:
        perms.append("submit_controlled_entity_intents")
    return perms


def _session(session_id: uuid.UUID) -> dict:
    row = execute_one("SELECT * FROM state.sessions WHERE id = %s", (str(session_id),))
    if not row:
        raise PlayerStateError("session_not_found", 404)
    return dict(row)


def _target_principal(
    *,
    session: dict,
    principal_id: uuid.UUID,
    as_principal_id: uuid.UUID | None,
) -> tuple[PrincipalContext, PrincipalContext]:
    campaign_id = uuid.UUID(str(session["campaign_id"]))
    requester = load_principal(principal_id, campaign_id)
    if not requester or not requester.role:
        raise PlayerStateError("forbidden", 403)

    if as_principal_id and str(as_principal_id) != str(principal_id):
        if not (requester.is_gm() or requester.is_system()):
            raise PlayerStateError("forbidden", 403)
        target = load_principal(as_principal_id, campaign_id)
        if not target or not target.role:
            raise PlayerStateError("forbidden", 403)
        return requester, target

    return requester, requester


def _controlled_entities(
    *,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    principal: PrincipalContext,
) -> list[dict]:
    if principal.is_gm() or principal.is_system():
        rows = execute_query(
            """
            SELECT e.*, sc.status AS session_status, sc.death_round, sc.death_details,
                   sc.revived_at, sc.revive_details
            FROM state.entities e
            LEFT JOIN state.session_characters sc
              ON sc.entity_id = e.id AND sc.session_id = %s
            WHERE e.campaign_id = %s AND e.entity_type = 'PC' AND e.status = 'ACTIVE'
            ORDER BY e.name
            """,
            (str(session_id), str(campaign_id)),
        )
    else:
        rows = execute_query(
            """
            SELECT e.*, sc.status AS session_status, sc.death_round, sc.death_details,
                   sc.revived_at, sc.revive_details
            FROM state.entities e
            LEFT JOIN state.session_characters sc
              ON sc.entity_id = e.id AND sc.session_id = %s
            WHERE e.campaign_id = %s
              AND e.controller_principal_id = %s
              AND e.status = 'ACTIVE'
              AND COALESCE(sc.status, 'ACTIVE') IN ('ACTIVE', 'DEAD')
            ORDER BY e.name
            """,
            (str(session_id), str(campaign_id), str(principal.principal_id)),
        )
    return [dict(r) for r in rows]


def _assert_principal_in_session(principal: PrincipalContext, controlled: list[dict]) -> None:
    role = str(principal.role.value if hasattr(principal.role, "value") else principal.role)
    if principal.is_gm() or principal.is_system() or role in {"OBSERVER", "GOD_OPERATOR"}:
        return
    if not controlled:
        raise PlayerStateError("principal_not_in_session", 403)


def _entity_snapshot(
    entity: dict,
    *,
    can_command: bool,
    include_private: bool = False,
) -> ControlledEntitySnapshot:
    sheet = entity.get("public_sheet") or {}
    return ControlledEntitySnapshot(
        entity_id=str(entity["id"]),
        name=entity["name"],
        kind=entity["entity_type"],
        current_map_id=str(entity["current_map_id"]) if entity.get("current_map_id") else None,
        position={"x": sheet.get("x"), "y": sheet.get("y")},
        stats={
            "hp_current": entity.get("hp_current"),
            "hp_max": entity.get("hp_max"),
            "ac": entity.get("ac"),
            "speed": entity.get("speed"),
        },
        resources=sheet.get("resources") or {},
        conditions=sheet.get("conditions") or [],
        inventory=sheet.get("inventory") or [],
        public_sheet=sheet,
        private_sheet=(entity.get("secret_sheet") or {}) if include_private else {},
        death_state=entity.get("session_status") or "ACTIVE",
        can_command=can_command and (entity.get("session_status") or "ACTIVE") == "ACTIVE",
    )


def _current_maps(controlled: list[dict]) -> list[dict]:
    map_ids = sorted({str(e.get("current_map_id")) for e in controlled if e.get("current_map_id")})
    if not map_ids:
        return []
    rows = execute_query(
        "SELECT id, campaign_id, name, kind, width, height, parent_map_id FROM state.maps WHERE id = ANY(%s::uuid[])",
        (map_ids,),
    )
    return [row_dict(r) for r in rows]


def _turn_state(
    *,
    campaign: dict,
    session: dict,
    controlled: list[dict],
    visible: list[dict],
) -> TurnStateSnapshot:
    encounter = execute_one(
        """
        SELECT * FROM state.encounters
        WHERE session_id = %s AND status = 'ACTIVE'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (str(session["id"]),),
    )
    active_slot = None
    if encounter:
        active_slot = execute_one(
            "SELECT * FROM state.encounter_slots WHERE encounter_id = %s AND is_active = true LIMIT 1",
            (str(encounter["id"]),),
        )
    legal = legal_actions_for(
        mode=campaign.get("mode") or "EXPLORATION",
        session_status=session.get("status") or "UNKNOWN",
        controlled_entities=controlled,
        visible_entities=visible,
        encounter=dict(encounter) if encounter else None,
        active_slot=dict(active_slot) if active_slot else None,
    )
    controlled_ids = {str(e["id"]) for e in controlled}
    active_entity_id = str(active_slot["entity_id"]) if active_slot else None
    return TurnStateSnapshot(
        mode=campaign.get("mode") or "EXPLORATION",
        encounter_id=str(encounter["id"]) if encounter else None,
        round=encounter.get("round_number") if encounter else None,
        active_entity_id=active_entity_id,
        is_my_turn=bool(active_entity_id and active_entity_id in controlled_ids),
        legal_actions=legal,
    )


def _narrative_state(
    *,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    principal: PrincipalContext,
    visible_entity_rows: list[dict],
) -> NarrativeStateSnapshot:
    story = execute_one("SELECT * FROM state.story_state WHERE session_id = %s", (str(session_id),))
    story = dict(story or {})
    visibility = "dm" if principal.is_gm() or principal.is_system() else "principal"
    principal_id = None if visibility == "dm" else str(principal.principal_id)

    npc_memory_map = {}
    for entity in visible_entity_rows:
        if entity.get("entity_type") == "NPC":
            npc_memory_map[str(entity["id"])] = npc_memory(
                campaign_id,
                str(entity["id"]),
                visibility=visibility,
                principal_id=principal_id,
            )

    is_dm = principal.is_gm() or principal.is_system()

    def visible_items(value):
        items = value or []
        if is_dm:
            return items
        cleaned = []
        for item in items:
            if isinstance(item, dict):
                cleaned.append({
                    k: v for k, v in item.items()
                    if k not in {"notes", "dm_notes", "dm_private_notes", "secret", "secrets"}
                })
            else:
                cleaned.append(item)
        return cleaned

    return NarrativeStateSnapshot(
        location=story.get("current_location"),
        game_time=story.get("game_time"),
        known_active_npcs=visible_items(story.get("active_npcs")),
        known_active_quests=visible_items(story.get("active_quests")),
        known_plot_threads=visible_items(story.get("plot_threads")),
        known_party_resources=story.get("party_resources") or {},
        visible_open_threads=open_threads(campaign_id, visibility=visibility, principal_id=principal_id),
        visible_unresolved_promises=unresolved_promises(campaign_id, visibility=visibility, principal_id=principal_id),
        visible_npc_memory=npc_memory_map,
    )


def build_player_state_snapshot(
    *,
    session_id: uuid.UUID,
    principal_id: uuid.UUID,
    as_principal_id: uuid.UUID | None = None,
    include_recent_events: bool = True,
    event_limit: int = 100,
) -> PlayerStateSnapshot:
    session = _session(session_id)
    requester, principal = _target_principal(
        session=session,
        principal_id=principal_id,
        as_principal_id=as_principal_id,
    )
    campaign_id = uuid.UUID(str(session["campaign_id"]))
    campaign = execute_one("SELECT * FROM state.campaigns WHERE id = %s", (str(campaign_id),))
    if not campaign:
        raise PlayerStateError("session_not_found", 404)

    controlled = _controlled_entities(session_id=session_id, campaign_id=campaign_id, principal=principal)
    _assert_principal_in_session(principal, controlled)
    visible = visible_entities(campaign_id=campaign_id, principal=principal, controlled_entities=controlled)
    recent, cursor = (
        visible_recent_events(session_id=session_id, principal_id=principal.principal_id, limit=event_limit)
        if include_recent_events else ([], {"last_ledger_id": None, "last_sequence": None})
    )
    turn_state = _turn_state(campaign=dict(campaign), session=session, controlled=controlled, visible=visible)
    selected = str(controlled[0]["id"]) if controlled else None

    return PlayerStateSnapshot(
        campaign_id=str(campaign_id),
        session_id=str(session_id),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        principal=PrincipalSnapshot(
            principal_id=str(principal.principal_id),
            role=str(principal.role.value if hasattr(principal.role, "value") else principal.role),
            permissions=_permissions(principal),
        ),
        controlled_entities=[
            _entity_snapshot(
                e,
                can_command=str(requester.principal_id) == str(principal_id) or requester.is_gm(),
                include_private=principal.is_gm() or principal.is_system(),
            )
            for e in controlled
        ],
        visible_world=VisibleWorldSnapshot(
            current_maps=_current_maps(controlled),
            visible_entities=visible,
            visible_pois=visible_pois(controlled),
            visible_decorations=visible_decorations(controlled),
            visible_recent_events=recent,
            event_cursor=EventCursor(**cursor),
        ),
        turn_state=turn_state,
        narrative_state=_narrative_state(
            session_id=session_id,
            campaign_id=campaign_id,
            principal=principal,
            visible_entity_rows=visible,
        ),
        ui_state=UiStateSnapshot(
            selected_entity_id=selected,
            command_locked=not bool(controlled),
            reconnect_required=False,
        ),
    )

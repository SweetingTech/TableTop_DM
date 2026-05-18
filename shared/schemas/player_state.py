from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class LegalAction(BaseModel):
    action: str
    enabled: bool
    reason: str | None = None
    requires_target: bool = False


class EventCursor(BaseModel):
    last_ledger_id: str | None = None
    last_sequence: int | None = None


class PrincipalSnapshot(BaseModel):
    principal_id: str
    role: str
    permissions: list[str] = Field(default_factory=list)


class ControlledEntitySnapshot(BaseModel):
    entity_id: str
    name: str
    kind: str
    current_map_id: str | None = None
    position: dict[str, int | None] = Field(default_factory=dict)
    stats: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    public_sheet: dict[str, Any] = Field(default_factory=dict)
    private_sheet: dict[str, Any] = Field(default_factory=dict)
    death_state: str = "ACTIVE"
    can_command: bool = True


class VisibleWorldSnapshot(BaseModel):
    current_maps: list[dict[str, Any]] = Field(default_factory=list)
    visible_entities: list[dict[str, Any]] = Field(default_factory=list)
    visible_pois: list[dict[str, Any]] = Field(default_factory=list)
    visible_decorations: list[dict[str, Any]] = Field(default_factory=list)
    visible_recent_events: list[dict[str, Any]] = Field(default_factory=list)
    event_cursor: EventCursor = Field(default_factory=EventCursor)


class TurnStateSnapshot(BaseModel):
    mode: str
    encounter_id: str | None = None
    round: int | None = None
    active_entity_id: str | None = None
    is_my_turn: bool = False
    legal_actions: list[LegalAction] = Field(default_factory=list)


class NarrativeStateSnapshot(BaseModel):
    location: str | None = None
    game_time: str | None = None
    known_active_npcs: list[Any] = Field(default_factory=list)
    known_active_quests: list[Any] = Field(default_factory=list)
    known_plot_threads: list[Any] = Field(default_factory=list)
    known_party_resources: dict[str, Any] = Field(default_factory=dict)
    visible_open_threads: list[dict[str, Any]] = Field(default_factory=list)
    visible_unresolved_promises: list[dict[str, Any]] = Field(default_factory=list)
    visible_npc_memory: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class UiStateSnapshot(BaseModel):
    selected_entity_id: str | None = None
    command_locked: bool = False
    reconnect_required: bool = False


class PlayerStateSnapshot(BaseModel):
    campaign_id: str
    session_id: str
    snapshot_version: Literal[1] = 1
    generated_at: str
    principal: PrincipalSnapshot
    controlled_entities: list[ControlledEntitySnapshot] = Field(default_factory=list)
    visible_world: VisibleWorldSnapshot = Field(default_factory=VisibleWorldSnapshot)
    turn_state: TurnStateSnapshot
    narrative_state: NarrativeStateSnapshot = Field(default_factory=NarrativeStateSnapshot)
    ui_state: UiStateSnapshot = Field(default_factory=UiStateSnapshot)

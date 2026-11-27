from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.parties import InvitationView, PartyView
from domains.tabletop.quests.contracts import QuestView


class SceneCoordinate(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: int
    y: int
    z: int = 0
    zone_id: uuid.UUID | str = "world"


class VisibleActivity(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["WEED", "REST", "EAT", "TRAVEL", "SLEEP", "SOCIAL"]
    status: Literal["RUNNING", "WAITING", "COMPLETED", "CANCELLED"]
    progress_percent: int = Field(ge=0, le=100)
    weeded_units: int = Field(ge=0)


class VisibleTradeOffer(BaseModel):
    model_config = ConfigDict(frozen=True)
    offer_id: uuid.UUID
    side: Literal["SELL", "BUY"]
    item: str
    quantity: int = Field(ge=1)
    unit_price: int = Field(ge=0)


class PerceivedEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    name: str | None = None
    apparent_type: str | None = None
    position: SceneCoordinate | None = None
    position_confidence: float = Field(ge=0, le=1)
    knowledge_state: Literal["VISIBLE", "LAST_KNOWN", "RUMORED"]
    detail_level: Literal["PRESENCE", "CLASSIFIED", "IDENTIFIED", "INSPECTED"]
    observed_at: datetime | None = None
    health: int | None = None
    max_health: int | None = None
    status: str | None = None
    mana: int | None = None
    guarded: bool | None = None
    attack_reach: int | None = None
    known_spell_ids: tuple[str, ...] | None = None
    action_wait_seconds: int | None = Field(default=None, ge=0)
    activity: VisibleActivity | None = None
    trade_offers: tuple[VisibleTradeOffer, ...] = ()
    quest_offers: tuple[QuestView, ...] = ()
    quests: tuple[QuestView, ...] = ()


class ObservationPresentation(BaseModel):
    model_config = ConfigDict(frozen=True)

    observation_id: uuid.UUID
    source_event_id: uuid.UUID
    event_type: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    observed_at: datetime
    immediate_source_entity_id: uuid.UUID | None = None


class PerceivedScene(BaseModel):
    model_config = ConfigDict(frozen=True)

    observer_entity_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    projection_version: int
    visible_zones: tuple[str, ...]
    perceived_entities: tuple[PerceivedEntity, ...]
    recent_observations: tuple[ObservationPresentation, ...]
    available_viewpoints: tuple[uuid.UUID, ...]
    parties: tuple[PartyView, ...] = ()
    party_invitations: tuple[InvitationView, ...] = ()
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def actionable_party_invitations(scene: PerceivedScene) -> tuple[InvitationView, ...]:
    visible = {
        entity.entity_id: entity
        for entity in scene.perceived_entities
        if entity.knowledge_state == "VISIBLE"
    }
    body = visible.get(scene.observer_entity_id)
    origin = body.position if body else None
    if origin is None:
        return ()
    choices: list[InvitationView] = []
    for invitation in scene.party_invitations:
        inviter = visible.get(invitation.inviter_id)
        location = inviter.position if inviter and inviter.status in {None, "ACTIVE"} else None
        if (
            location is None
            or (str(location.zone_id), location.z) != (str(origin.zone_id), origin.z)
            or max(abs(location.x - origin.x), abs(location.y - origin.y)) > 1
        ):
            continue
        choices.append(invitation)
        if len(choices) == 8:
            break
    return tuple(choices)

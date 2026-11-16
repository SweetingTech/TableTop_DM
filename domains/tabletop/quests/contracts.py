"""Immutable public quest definitions and private canonical evidence records."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUESTS = "tabletop.quest_contracts"
QUEST_VERSION = "tabletop-quests-2.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ObjectiveBase(StrictModel):
    description: str = Field(min_length=1, max_length=160)


class DefeatObjective(ObjectiveBase):
    kind: Literal["DEFEAT"]
    target_ids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=32)

    @field_validator("target_ids")
    @classmethod
    def distinct_targets(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("defeat targets must be distinct")
        return values


class MoveObjective(ObjectiveBase):
    kind: Literal["MOVE"]
    zone_id: str = Field(default="world", min_length=1, max_length=120)
    x: int = Field(ge=-100000, le=100000)
    y: int = Field(ge=-100000, le=100000)
    z: int = Field(default=0, ge=-1000, le=1000)


class WorkObjective(ObjectiveBase):
    kind: Literal["WEED"]
    units: int = Field(ge=1, le=1000000)


class TradeObjective(ObjectiveBase):
    kind: Literal["TRADE"]
    side: Literal["BUY", "SELL"]
    counterparty_id: uuid.UUID
    item: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    quantity: int = Field(ge=1, le=100000)


Objective = Annotated[
    DefeatObjective | MoveObjective | WorkObjective | TradeObjective, Field(discriminator="kind")
]
Item = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")]
Count = Annotated[int, Field(ge=1, le=100000)]


class ConfigureQuest(StrictModel):
    giver_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    objectives: tuple[Objective, ...] = Field(min_length=1, max_length=8)
    reward_gold: int = Field(default=0, ge=0, le=1000000)
    reward_items: dict[Item, Count] = Field(default_factory=dict, max_length=16)


class Evidence(StrictModel):
    progress: int = Field(default=0, ge=0)
    seen_entity_ids: tuple[uuid.UUID, ...] = ()
    last_source_command_id: uuid.UUID | None = None


class Quest(ConfigureQuest):
    quest_id: uuid.UUID
    rules_version: str = QUEST_VERSION
    run_id: uuid.UUID
    source_command_id: uuid.UUID
    created_sequence: int = Field(ge=0)
    owner_id: uuid.UUID | None = None
    status: Literal["OFFERED", "ACTIVE", "READY", "CLAIMED", "CANCELLED"] = "OFFERED"
    evidence: tuple[Evidence, ...]


class QuestReference(StrictModel):
    quest_id: uuid.UUID


class ObjectiveView(StrictModel):
    description: str
    progress: int
    target: int


class QuestView(StrictModel):
    quest_id: uuid.UUID
    title: str
    description: str
    status: str
    objectives: tuple[ObjectiveView, ...]
    reward_gold: int
    reward_items: dict[str, int]


class QuestResult(QuestView):
    summary: str


def target(objective: Objective) -> int:
    if isinstance(objective, DefeatObjective):
        return len(objective.target_ids)
    if isinstance(objective, WorkObjective):
        return objective.units
    if isinstance(objective, TradeObjective):
        return objective.quantity
    return 1


def view(quest: Quest) -> QuestView:
    return QuestView(
        quest_id=quest.quest_id,
        title=quest.title,
        description=quest.description,
        status=quest.status,
        reward_gold=quest.reward_gold,
        reward_items=quest.reward_items,
        objectives=tuple(
            ObjectiveView(description=o.description, progress=e.progress, target=target(o))
            for o, e in zip(quest.objectives, quest.evidence, strict=True)
        ),
    )


def result(quest: Quest, summary: str) -> dict:
    return QuestResult(**view(quest).model_dump(), summary=summary).model_dump(mode="json")

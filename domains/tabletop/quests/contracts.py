"""Immutable public quest definitions and private canonical evidence records."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUESTS = "tabletop.quest_contracts"
QUEST_VERSION = "tabletop-quests-2.1.0"


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


class QuestApproach(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    objectives: tuple[Objective, ...] = Field(min_length=1, max_length=8)


class ConfigureQuest(StrictModel):
    giver_id: uuid.UUID
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1000)
    objectives: tuple[Objective, ...] = Field(min_length=1, max_length=8)
    alternate_approaches: tuple[QuestApproach, ...] = Field(default=(), max_length=4)
    alternate_giver_ids: tuple[uuid.UUID, ...] = Field(default=(), max_length=8)
    required_items: dict[Item, Count] = Field(default_factory=dict, max_length=16)
    transferable: bool = Field(default=False, strict=True)
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
    alternate_evidence: tuple[tuple[Evidence, ...], ...] = ()
    transfer_recipient_id: uuid.UUID | None = None
    transfer_event_id: uuid.UUID | None = None


class QuestReference(StrictModel):
    quest_id: uuid.UUID


class TransferQuest(QuestReference):
    recipient_id: uuid.UUID


class ObjectiveView(StrictModel):
    description: str
    progress: int
    target: int


class ApproachView(StrictModel):
    title: str
    objectives: tuple[ObjectiveView, ...]


class QuestView(StrictModel):
    quest_id: uuid.UUID
    title: str
    description: str
    status: str
    objectives: tuple[ObjectiveView, ...]
    alternate_approaches: tuple[ApproachView, ...] = Field(
        default=(), exclude_if=lambda rows: not rows
    )
    required_items: dict[str, int] = Field(default_factory=dict, exclude_if=lambda items: not items)
    reward_gold: int
    reward_items: dict[str, int]


class QuestResult(QuestView):
    summary: str
    transfer_event_id: uuid.UUID | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


def target(objective: Objective) -> int:
    if isinstance(objective, DefeatObjective):
        return len(objective.target_ids)
    if isinstance(objective, WorkObjective):
        return objective.units
    if isinstance(objective, TradeObjective):
        return objective.quantity
    return 1


def objective_views(
    objectives: tuple[Objective, ...], evidence: tuple[Evidence, ...]
) -> tuple[ObjectiveView, ...]:
    return tuple(
        ObjectiveView(description=o.description, progress=e.progress, target=target(o))
        for o, e in zip(objectives, evidence, strict=True)
    )


def view(quest: Quest, *, transfer_offer: bool = False) -> QuestView:
    return QuestView(
        quest_id=quest.quest_id,
        title=quest.title,
        description=quest.description,
        status="OFFERED" if transfer_offer else quest.status,
        reward_gold=quest.reward_gold,
        reward_items=quest.reward_items,
        objectives=objective_views(quest.objectives, quest.evidence),
        alternate_approaches=tuple(
            ApproachView(
                title=approach.title, objectives=objective_views(approach.objectives, proof)
            )
            for approach, proof in zip(
                quest.alternate_approaches, quest.alternate_evidence, strict=True
            )
        ),
        required_items=quest.required_items,
    )


def result(quest: Quest, summary: str, *, transfer_event_id: uuid.UUID | None = None) -> dict:
    return QuestResult(
        **view(quest).model_dump(), summary=summary, transfer_event_id=transfer_event_id
    ).model_dump(mode="json")

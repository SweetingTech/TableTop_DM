from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_serializer, field_validator

from domains.tabletop.character_identity import CharacterIdentity
from kernel.state import stable_hash

if TYPE_CHECKING:
    from domains.tabletop.portal import CharacterRecord


@dataclass(frozen=True)
class FrozenScores(Mapping[str, int]):
    entries: tuple[tuple[str, int], ...]

    def __getitem__(self, key: str) -> int:
        for name, value in self.entries:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)


class CharacterCardContent(BaseModel):
    """Authored identity only; no account, controller, wounds, or learned evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid", serialize_by_alias=True)
    schema_tag: Literal["character-card-1.0.0"] = Field(
        default="character-card-1.0.0", alias="schema"
    )
    name: str
    species: str
    class_name: str
    background: str
    level: int
    ability_scores: Mapping[str, int]
    authored_identity: CharacterIdentity = Field(default_factory=CharacterIdentity)

    @field_validator("ability_scores", mode="after")
    @classmethod
    def freeze_scores(cls, value: Mapping[str, int]) -> Mapping[str, int]:
        return FrozenScores(tuple(sorted(value.items())))

    @field_serializer("ability_scores")
    def serialize_scores(self, value: Mapping[str, int]) -> dict[str, int]:
        return dict(value)

    @classmethod
    def from_record(cls, record: CharacterRecord) -> CharacterCardContent:
        return cls.model_validate(
            record.model_dump(
                include={
                    "name",
                    "species",
                    "class_name",
                    "background",
                    "level",
                    "ability_scores",
                    "authored_identity",
                }
            )
        )

    @property
    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json", by_alias=True))


class CharacterCardRevision(BaseModel):
    model_config = ConfigDict(frozen=True)
    revision_id: uuid.UUID
    character_id: uuid.UUID
    revision_number: int = Field(ge=1)
    content: CharacterCardContent
    recorded_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def card_version(self) -> str:
        return self.content.content_hash

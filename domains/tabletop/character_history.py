from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from domains.tabletop.character_identity import CharacterIdentity
from kernel.state import stable_hash

if TYPE_CHECKING:
    from domains.tabletop.portal import CharacterRecord


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
    ability_scores: dict[str, int]
    authored_identity: CharacterIdentity = Field(default_factory=CharacterIdentity)

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

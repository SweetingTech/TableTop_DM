"""Read-only retrieval over learned claims, never over the world's lore catalog."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cognition.models import Observation
from domains.tabletop.character_history import CharacterCardContent
from kernel.state import stable_hash

KNOWLEDGE_VERSION = "character-knowledge-1.0.0"


class KnownLore(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=12000)
    kind: Literal["AUTHORED_CLAIM", "TESTIMONY", "EXPERIENCE"]
    confidence: float = Field(ge=0, le=1)
    source_event_id: uuid.UUID | None = None
    source_observation_id: uuid.UUID | None = None
    source_card_hash: str | None = None
    source_order: int

    def fiction(self) -> dict:
        return {
            "text": self.text,
            "basis": "recollection" if self.kind == "AUTHORED_CLAIM" else self.kind.lower(),
            "confidence": self.confidence,
        }


def knowledge_from_validated(
    observations: tuple[Observation, ...], identity: CharacterCardContent | None
) -> tuple[KnownLore, ...]:
    """Trusted caller has already validated every source against this body's branch/grant."""
    items: dict[tuple[str, str], KnownLore] = {}
    if identity is not None:
        card_hash = stable_hash(identity.model_dump(mode="json"))
        for index, text in enumerate(identity.authored_identity.initial_known_facts):
            items[("AUTHORED_CLAIM", text)] = KnownLore(
                text=text,
                kind="AUTHORED_CLAIM",
                confidence=1,
                source_card_hash=card_hash,
                source_order=index - 20,
            )
    for index, observation in enumerate(observations):
        facts = observation.perceived_payload
        observed_text = facts.get("text", facts.get("summary"))
        if (
            not isinstance(observed_text, str)
            or not observed_text.strip()
            or len(observed_text) > 12000
        ):
            continue
        kind = "TESTIMONY" if facts.get("speaker_entity_id") else "EXPERIENCE"
        text = observed_text.strip()
        items[(kind, text)] = KnownLore(
            text=text,
            kind=kind,
            confidence=observation.confidence,
            source_event_id=observation.source_event_id,
            source_observation_id=observation.observation_id,
            source_order=index,
        )
    return tuple(sorted(items.values(), key=lambda item: (item.source_order, item.kind, item.text)))


def search_known_lore(
    items: tuple[KnownLore, ...], query: str = "", *, limit: int = 5
) -> tuple[KnownLore, ...]:
    if not 1 <= limit <= 20 or len(query) > 400:
        raise ValueError("knowledge query requires at most 400 characters and limit 1–20")
    tokens = set(re.findall(r"\w+", query.casefold()))
    ranked = []
    for item in items:
        words = set(re.findall(r"\w+", item.text.casefold()))
        score = len(tokens & words) / len(tokens | words) if tokens else 0
        if not tokens or score:
            ranked.append((score, item))
    return tuple(
        item
        for _, item in sorted(
            ranked, key=lambda row: (-row[0], -row[1].source_order, row[1].kind, row[1].text)
        )[:limit]
    )

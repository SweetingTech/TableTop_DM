from __future__ import annotations

import json
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field

from cognition.models import Memory, Observation

_TOKEN = re.compile(r"[a-z0-9]+")


class RecalledMemory(BaseModel):
    model_config = ConfigDict(frozen=True)

    memory: Memory
    score: float = Field(ge=0)


class MemoryEngine:
    VERSION = "memory-1.0.0"

    def record(
        self,
        observation: Observation,
        *,
        summary: str | None = None,
        emotional_weight: float = 0.0,
        importance: float = 0.5,
        visibility: str = "PRIVATE",
    ) -> Memory:
        if summary is None:
            summary = json.dumps(
                observation.perceived_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        summary = summary.strip()
        if not summary:
            raise ValueError("Memory summary cannot be empty")
        if not -1 <= emotional_weight <= 1:
            raise ValueError("emotional_weight must be between -1 and 1")
        if not 0 <= importance <= 1:
            raise ValueError("importance must be between 0 and 1")
        memory_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            ":".join(
                (
                    "tabletop-dm:memory",
                    self.VERSION,
                    str(observation.observer_entity_id),
                    str(observation.source_event_id),
                    summary,
                )
            ),
        )
        starting_strength = round(
            min(1.0, 0.45 + 0.4 * importance + 0.15 * abs(emotional_weight)), 6
        )
        return Memory(
            memory_id=memory_id,
            entity_id=observation.observer_entity_id,
            source_event_id=observation.source_event_id,
            summary=summary,
            emotional_weight=emotional_weight,
            importance=importance,
            recall_strength=starting_strength,
            visibility=visibility,
            created_at=observation.observed_at,
        )

    @staticmethod
    def decay(
        memories: tuple[Memory, ...],
        *,
        elapsed_steps: int,
        decay_rate: float = 0.02,
    ) -> tuple[Memory, ...]:
        if elapsed_steps < 0:
            raise ValueError("elapsed_steps cannot be negative")
        if not 0 <= decay_rate <= 1:
            raise ValueError("decay_rate must be between 0 and 1")
        decayed: list[Memory] = []
        for memory in memories:
            effective_rate = decay_rate * (1 - 0.5 * memory.importance)
            strength = round(
                max(0.0, memory.recall_strength * (1 - effective_rate) ** elapsed_steps),
                6,
            )
            decayed.append(memory.model_copy(update={"recall_strength": strength}))
        return tuple(decayed)

    @staticmethod
    def recall(
        memories: tuple[Memory, ...],
        query: str,
        *,
        limit: int = 5,
        allowed_visibilities: frozenset[str] | None = None,
    ) -> tuple[RecalledMemory, ...]:
        if limit < 0:
            raise ValueError("limit cannot be negative")
        query_tokens = set(_TOKEN.findall(query.lower()))
        recalled: list[RecalledMemory] = []
        for memory in memories:
            if allowed_visibilities is not None and memory.visibility not in allowed_visibilities:
                continue
            memory_tokens = set(_TOKEN.findall(memory.summary.lower()))
            lexical = len(query_tokens & memory_tokens) / len(query_tokens) if query_tokens else 0.0
            score = round(
                0.45 * lexical
                + 0.3 * memory.importance
                + 0.2 * memory.recall_strength
                + 0.05 * abs(memory.emotional_weight),
                6,
            )
            recalled.append(RecalledMemory(memory=memory, score=score))
        recalled.sort(key=lambda item: (-item.score, str(item.memory.memory_id)))
        return tuple(recalled[:limit])

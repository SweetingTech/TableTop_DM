"""Narration derived from scoped, committed facts and frozen observations."""

from __future__ import annotations

import threading
import uuid
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from cognition.context import validated_observations
from cognition.dialogue_generation import fiction
from cognition.models import Observation
from domains.tabletop.spatial.service import require_scene_access
from kernel.application import SimulationApplication, stable_id
from kernel.perception_contracts import NON_SENSORY_TAGS, SensoryModality

NarrationAudience = Literal["OPERATOR", "SPECTATOR", "CHARACTER"]
NARRATION_VERSION = "narration-1.0.0"


class NarrationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: uuid.UUID
    audience: NarrationAudience
    observer_entity_id: uuid.UUID | None = None
    after_event_id: uuid.UUID | None = None
    limit: int = Field(default=12, ge=1, le=32)

    @model_validator(mode="after")
    def viewpoint_matches_audience(self) -> NarrationRequest:
        if (self.audience == "OPERATOR") != (self.observer_entity_id is None):
            raise ValueError("a viewpoint is required for spectator and character narration")
        return self


class NarrationEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    narration_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    audience: NarrationAudience
    observer_entity_id: uuid.UUID | None
    source_event_id: uuid.UUID
    source_observation_id: uuid.UUID | None
    occurred_at: AwareDatetime
    version: str = NARRATION_VERSION
    text: str = Field(min_length=1, max_length=850)


class NarrationRepository(Protocol):
    def retain(
        self, entries: tuple[NarrationEntry, ...], *, actor_id: uuid.UUID
    ) -> tuple[NarrationEntry, ...]: ...

    def get(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        narration_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> NarrationEntry | None: ...


class InMemoryNarrations:
    def __init__(self) -> None:
        self._entries: dict[tuple[uuid.UUID, uuid.UUID], NarrationEntry] = {}
        self._lock = threading.RLock()

    def retain(
        self, entries: tuple[NarrationEntry, ...], *, actor_id: uuid.UUID
    ) -> tuple[NarrationEntry, ...]:
        with self._lock:
            return tuple(
                self._entries.setdefault((actor_id, entry.narration_id), entry) for entry in entries
            )

    def get(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        narration_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> NarrationEntry | None:
        with self._lock:
            entry = self._entries.get((actor_id, narration_id))
            if entry is not None and (entry.world_id, entry.branch_id) == (world_id, branch_id):
                return entry
        return None


def require_narration_access(
    simulation: SimulationApplication,
    *,
    world_id: uuid.UUID,
    branch_id: uuid.UUID,
    run_id: uuid.UUID,
    actor_id: uuid.UUID,
    audience: NarrationAudience,
    observer_entity_id: uuid.UUID | None,
) -> None:
    run = simulation.runs.get(run_id)
    if run is None or (run.world_id, run.branch_id) != (world_id, branch_id):
        raise ValueError("narration run does not belong to this world branch")
    actor = simulation.authority(world_id, actor_id)
    if "world.read" not in actor.capabilities:
        raise PermissionError("actor cannot read this world")
    if audience == "OPERATOR":
        if "world.read.all" not in actor.capabilities:
            raise PermissionError("operator narration requires world-wide read authority")
        return
    if observer_entity_id is None:
        raise ValueError("narration viewpoint is required")
    require_scene_access(
        simulation,
        world_id=world_id,
        branch_id=branch_id,
        observer_entity_id=observer_entity_id,
        actor_id=actor_id,
    )
    if not {"world.read.all", "mind.read.all"}.intersection(actor.capabilities):
        entity = simulation.entities[(branch_id, observer_entity_id)]
        if entity.controller_actor_id == actor_id:
            return
        if not any(
            (row.world_id, row.branch_id, row.entity_id)
            == (world_id, branch_id, observer_entity_id)
            and (
                (row.owner_actor_id == actor_id and row.last_error != "seat_removed")
                or (row.executor_actor_id == actor_id and row.mode == "AUTONOMOUS")
            )
            for row in simulation.controller_states.values()
        ):
            raise PermissionError("actor cannot inspect this embodied viewpoint")


def _line(event_type: str, payload: dict[str, Any], audience: NarrationAudience) -> str | None:
    character = audience == "CHARACTER"
    if event_type == "tabletop.spatial.move":
        destination = payload.get("destination")
        if isinstance(destination, dict) and all(
            type(destination.get(axis)) is int for axis in ("x", "y")
        ):
            moving = "You see someone move" if character else "Someone moves"
            return f"{moving} to ({destination['x']}, {destination['y']})."
    if event_type == "tabletop.dialogue.speak" and audience != "SPECTATOR":
        spoken = payload.get("text")
        line = fiction(" ".join(spoken.split())) if isinstance(spoken, str) else ""
        if line:
            prefix = "You hear" if character else "A voice says"
            return f"{prefix} “{line}”"
    if event_type == "tabletop.combat.attack":
        hit = payload.get("hit")
        if hit is True:
            return "A strike lands."
        if hit is False:
            return "A strike misses."
    if event_type in {"tabletop.magic.invoke", "tabletop.magic.cast"}:
        if "spell_id" in payload:
            return "Someone casts a spell."
    return None


def build_narration(
    simulation: SimulationApplication,
    *,
    world_id: uuid.UUID,
    branch_id: uuid.UUID,
    actor_id: uuid.UUID,
    request: NarrationRequest,
    observations: tuple[Observation, ...] = (),
) -> tuple[NarrationEntry, ...]:
    require_narration_access(
        simulation,
        world_id=world_id,
        branch_id=branch_id,
        run_id=request.run_id,
        actor_id=actor_id,
        audience=request.audience,
        observer_entity_id=request.observer_entity_id,
    )
    observer = request.observer_entity_id
    experienced = (
        validated_observations(
            observations,
            world_id=world_id,
            branch_id=branch_id,
            entity_id=observer,
            actor_id=actor_id,
            event_reader=simulation.events.get,
            grant_reader=lambda event_id, entity_id: simulation.perceptions.get(
                (event_id, entity_id)
            ),
        )
        if observer is not None
        else ()
    )
    by_source = {item.source_event_id: item for item in experienced}
    entries: list[NarrationEntry] = []
    for event in simulation.events.values():
        if (event.world_id, event.branch_id, event.run_id) != (
            world_id,
            branch_id,
            request.run_id,
        ) or NON_SENSORY_TAGS.intersection(event.domain_tags):
            continue
        knowledge = by_source.get(event.event_id)
        if observer is not None and knowledge is None:
            continue
        if request.audience == "SPECTATOR" and observer is not None:
            grant = simulation.perceptions[(event.event_id, observer)]
            if SensoryModality.SIGHT not in grant.modalities:
                continue
        line = _line(
            event.event_type,
            event.payload if knowledge is None else knowledge.perceived_payload,
            request.audience,
        )
        if line is None:
            continue
        entries.append(
            NarrationEntry(
                narration_id=stable_id(
                    f"{NARRATION_VERSION}:{actor_id}:{request.audience}:{observer}:{event.event_id}"
                ),
                world_id=world_id,
                branch_id=branch_id,
                run_id=request.run_id,
                audience=request.audience,
                observer_entity_id=observer,
                source_event_id=event.event_id,
                source_observation_id=knowledge.observation_id if knowledge else None,
                occurred_at=event.created_at,
                text=line,
            )
        )
    if request.after_event_id is None:
        return tuple(entries[-request.limit :])
    for index, entry in enumerate(entries):
        if entry.source_event_id == request.after_event_id:
            return tuple(entries[index + 1 : index + 1 + request.limit])
    raise KeyError(request.after_event_id)

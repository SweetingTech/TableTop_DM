from __future__ import annotations

import uuid
from datetime import datetime

from cognition.context import validated_observations
from cognition.models import Observation
from cognition.store import MindStore
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from domains.tabletop.spatial.scene import (
    ObservationPresentation,
    PerceivedEntity,
    PerceivedScene,
    SceneCoordinate,
)
from kernel.application import SimulationApplication


def build_perceived_scene(
    simulation: SimulationApplication,
    minds: MindStore,
    *,
    world_id: uuid.UUID,
    branch_id: uuid.UUID,
    observer_entity_id: uuid.UUID,
    actor_id: uuid.UUID,
) -> PerceivedScene:
    state = simulation.states.get(branch_id)
    if state.world_id != world_id:
        raise ValueError("scene branch does not belong to world")
    actor = simulation.authority(world_id, actor_id)
    observer = simulation.entities.get((branch_id, observer_entity_id))
    if observer is None or observer.world_id != world_id or observer.branch_id != branch_id:
        raise KeyError(observer_entity_id)
    privileged = "world.read.all" in actor.capabilities or "mind.read.all" in actor.capabilities
    if observer_entity_id not in actor.controlled_entity_ids and not privileged:
        raise PermissionError("actor cannot inspect this embodied viewpoint")
    viewpoints = tuple(
        sorted(
            (
                entity_id
                for (entity_branch, entity_id), _entity in simulation.entities.items()
                if entity_branch == branch_id
                and (privileged or entity_id in actor.controlled_entity_ids)
            ),
            key=str,
        )
    )
    resolver = simulation.bus.event_factory.resolver
    if not isinstance(resolver, GridSpatialPerceptionResolver):
        raise RuntimeError("tabletop scene requires the grid spatial resolver")
    visible = resolver.visible_entities(state, observer_entity_id)
    projected_entities = state.projections.get("tabletop.entities", {})
    spatial_positions = state.projections.get("tabletop.spatial.positions", {})
    entities: list[PerceivedEntity] = []
    for entity_id, confidence in sorted(visible.items(), key=lambda item: str(item[0])):
        record = simulation.entities.get((branch_id, entity_id))
        if record is None:
            continue
        current = projected_entities.get(str(entity_id), record.public_state)
        position = spatial_positions.get(str(entity_id), current)
        if confidence >= 0.8:
            detail = "INSPECTED"
        elif confidence >= 0.5:
            detail = "IDENTIFIED"
        elif confidence >= 0.2:
            detail = "CLASSIFIED"
        else:
            detail = "PRESENCE"
        identified = detail in {"IDENTIFIED", "INSPECTED"} or entity_id == observer_entity_id
        classified = detail != "PRESENCE" or entity_id == observer_entity_id
        inspected = detail == "INSPECTED" or entity_id == observer_entity_id
        entities.append(
            PerceivedEntity(
                entity_id=entity_id,
                name=record.name if identified else None,
                apparent_type=record.entity_type if classified else None,
                position=(
                    SceneCoordinate(
                        x=int(position["x"]),
                        y=int(position["y"]),
                        z=int(position.get("z", 0)),
                        zone_id=position.get("zone_id", current.get("zone_id", "world")),
                    )
                    if "x" in position and "y" in position
                    else None
                ),
                position_confidence=confidence,
                knowledge_state="VISIBLE",
                detail_level=detail,
                health=int(current["hp"]) if inspected and "hp" in current else None,
                max_health=(int(current["max_hp"]) if inspected and "max_hp" in current else None),
                status=("DEFEATED" if current.get("defeated") else "ACTIVE") if inspected else None,
            )
        )
    mind = minds.inspect(observer_entity_id, branch_id=branch_id)
    observation_presentations: list[ObservationPresentation] = []
    observations = validated_observations(
        tuple(Observation.model_validate(item) for item in mind["observations"]),
        world_id=world_id,
        branch_id=branch_id,
        entity_id=observer_entity_id,
        actor_id=actor_id,
        event_reader=simulation.events.get,
        grant_reader=lambda event_id, entity_id: simulation.perceptions.get((event_id, entity_id)),
    )
    for observation_model in observations[-80:]:
        observation = observation_model.model_dump(mode="json")
        source_event = simulation.events.get(uuid.UUID(str(observation["source_event_id"])))
        if source_event is None:
            continue
        payload = observation["perceived_payload"]
        observation_presentations.append(
            ObservationPresentation(
                observation_id=uuid.UUID(str(observation["observation_id"])),
                source_event_id=source_event.event_id,
                event_type=source_event.event_type,
                summary=str(
                    payload.get("summary") or payload.get("text") or source_event.event_type
                ),
                confidence=float(observation["confidence"]),
                observed_at=datetime.fromisoformat(str(observation["observed_at"])),
                immediate_source_entity_id=(
                    uuid.UUID(str(payload["speaker_entity_id"]))
                    if payload.get("speaker_entity_id")
                    else None
                ),
            )
        )
    visible_zones = tuple(
        sorted({str(item.position.zone_id) for item in entities if item.position is not None})
    )
    scene = PerceivedScene(
        observer_entity_id=observer_entity_id,
        world_id=world_id,
        branch_id=branch_id,
        projection_version=state.version,
        visible_zones=visible_zones,
        perceived_entities=tuple(entities),
        recent_observations=tuple(observation_presentations),
        available_viewpoints=viewpoints,
    )
    return scene

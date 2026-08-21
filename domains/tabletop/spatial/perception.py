from __future__ import annotations

import math
import uuid
from collections import deque

from kernel.contracts import CommandProposal
from kernel.perception_contracts import (
    AudienceResolution,
    EventEmission,
    PerceptionGrant,
    PerceptionOutcome,
    SensoryModality,
)
from kernel.state import BranchState, stable_hash

from .models import SpatialOccluder, SpatialPortal, SpatialPosition, SpatialZone


class GridSpatialPerceptionResolver:
    """Deterministic grid sight/sound resolver over event-time projections."""

    VERSION = "grid-spatial-perception-1.0.0"

    def visible_entities(
        self,
        state: BranchState,
        observer_entity_id: uuid.UUID,
        *,
        max_range: float = 12.0,
    ) -> dict[uuid.UUID, float]:
        """Return current sight confidence without exposing the canonical projection."""
        positions = self._positions(state)
        observer = positions.get(observer_entity_id)
        if observer is None:
            return {}
        zones = self._zones(state)
        occluders = self._occluders(state)
        profiles = state.projections.get("tabletop.sensory_profiles", {})
        visible: dict[uuid.UUID, float] = {observer_entity_id: 1.0}
        for target_id, target in sorted(positions.items(), key=lambda item: str(item[0])):
            if target_id == observer_entity_id or profiles.get(str(target_id), {}).get("invisible"):
                continue
            confidence, _ = self._sight_confidence(
                target,
                observer,
                EventEmission(
                    anchor={"entity_id": target_id, "phase": "AFTER"},
                    modalities=(SensoryModality.SIGHT,),
                    max_range=max_range,
                ),
                zones,
                occluders,
            )
            if confidence > 0:
                visible[target_id] = round(confidence, 6)
        return visible

    def resolve(
        self,
        *,
        event_id: uuid.UUID,
        proposal: CommandProposal,
        emission: EventEmission | None,
        before: BranchState,
        after: BranchState,
    ) -> AudienceResolution:
        if emission is None or not emission.modalities:
            return AudienceResolution()
        anchor_state = before if emission.anchor.phase == "BEFORE" else after
        positions = self._positions(anchor_state)
        origin = self._origin(emission, positions)
        if origin is None:
            return AudienceResolution()
        zones = self._zones(anchor_state)
        portals = self._portals(anchor_state)
        occluders = self._occluders(anchor_state)
        sensor_profiles = anchor_state.projections.get("tabletop.sensory_profiles", {})
        context_hash = stable_hash(
            {
                "before_hash": before.state_hash,
                "after_hash": after.state_hash,
                "emission": emission.model_dump(mode="json"),
                "positions": {
                    str(key): value.model_dump(mode="json")
                    for key, value in sorted(positions.items(), key=lambda item: str(item[0]))
                },
                "zones": {str(key): value.model_dump(mode="json") for key, value in zones.items()},
                "portals": [item.model_dump(mode="json") for item in portals],
                "occluders": [item.model_dump(mode="json") for item in occluders],
                "sensor_profiles": sensor_profiles,
                "resolver_version": self.VERSION,
            }
        )
        grants: list[PerceptionGrant] = []
        for entity_id, observer in sorted(positions.items(), key=lambda item: str(item[0])):
            profile = sensor_profiles.get(str(entity_id), {})
            perceived: list[SensoryModality] = []
            confidences: list[float] = []
            reasons: list[str] = list(emission.reason_codes)
            if SensoryModality.SOUND in emission.modalities and not profile.get("deafened"):
                confidence, sound_reasons = self._sound_confidence(
                    origin, observer, emission, zones, portals, occluders
                )
                if confidence > 0:
                    perceived.append(SensoryModality.SOUND)
                    confidences.append(confidence * float(profile.get("hearing_acuity", 1.0)))
                    reasons.extend(sound_reasons)
            if SensoryModality.SIGHT in emission.modalities and not profile.get("blinded"):
                confidence, sight_reasons = self._sight_confidence(
                    origin, observer, emission, zones, occluders
                )
                if confidence > 0:
                    perceived.append(SensoryModality.SIGHT)
                    confidences.append(confidence * float(profile.get("sight_acuity", 1.0)))
                    reasons.extend(sight_reasons)
            if not perceived:
                continue
            confidence = round(max(0.0, min(1.0, max(confidences))), 6)
            controller = profile.get("controller_actor_id")
            if entity_id == proposal.embodied_entity_id:
                controller = proposal.actor_id
            grants.append(
                PerceptionGrant(
                    event_id=event_id,
                    world_id=proposal.world_id,
                    branch_id=proposal.branch_id,
                    observer_entity_id=entity_id,
                    controller_actor_id=uuid.UUID(str(controller)) if controller else None,
                    modalities=tuple(sorted(set(perceived), key=lambda item: item.value)),
                    outcome=(
                        PerceptionOutcome.DIRECT
                        if confidence >= 0.75
                        else PerceptionOutcome.PARTIAL
                    ),
                    confidence=confidence,
                    allowed_payload_fields=emission.allowed_payload_fields,
                    hidden_payload_fields=emission.hidden_payload_fields,
                    payload_overrides=emission.payload_overrides,
                    reason_codes=tuple(sorted(set(reasons))),
                    resolver_version=self.VERSION,
                    spatial_context_hash=context_hash,
                )
            )
        return AudienceResolution(perceptions=tuple(grants))

    @staticmethod
    def _positions(state: BranchState) -> dict[uuid.UUID, SpatialPosition]:
        values: dict[uuid.UUID, SpatialPosition] = {}
        entities = state.projections.get("tabletop.entities", {})
        explicit = state.projections.get("tabletop.spatial.positions", {})
        for raw_id, entity in entities.items():
            spatial = explicit.get(raw_id, entity)
            if "x" not in spatial or "y" not in spatial:
                continue
            entity_id = uuid.UUID(str(raw_id))
            values[entity_id] = SpatialPosition(
                entity_id=entity_id,
                zone_id=spatial.get("zone_id", entity.get("zone_id", "world")),
                x=int(spatial["x"]),
                y=int(spatial["y"]),
                z=int(spatial.get("z", entity.get("z", 0))),
                facing=spatial.get("facing", entity.get("facing")),
            )
        return values

    @staticmethod
    def _zones(state: BranchState) -> dict[str, SpatialZone]:
        result = {"world": SpatialZone(zone_id="world", name="World")}
        for key, value in state.projections.get("tabletop.spatial.zones", {}).items():
            result[str(key)] = SpatialZone.model_validate({"zone_id": key, **value})
        return result

    @staticmethod
    def _portals(state: BranchState) -> tuple[SpatialPortal, ...]:
        return tuple(
            SpatialPortal.model_validate({"portal_id": key, **value})
            for key, value in sorted(state.projections.get("tabletop.spatial.portals", {}).items())
        )

    @staticmethod
    def _occluders(state: BranchState) -> tuple[SpatialOccluder, ...]:
        explicit = list(state.projections.get("tabletop.spatial.occluders", {}).values())
        legacy = list(state.projections.get("tabletop.obstacles", {}).values())
        return tuple(SpatialOccluder.model_validate(value) for value in (*explicit, *legacy))

    @staticmethod
    def _origin(
        emission: EventEmission, positions: dict[uuid.UUID, SpatialPosition]
    ) -> SpatialPosition | None:
        if emission.anchor.phase == "EXPLICIT":
            if emission.anchor.x is None or emission.anchor.y is None:
                return None
            return SpatialPosition(
                entity_id=emission.anchor.entity_id or uuid.UUID(int=0),
                zone_id=emission.anchor.zone_id or "world",
                x=round(emission.anchor.x),
                y=round(emission.anchor.y),
                z=round(emission.anchor.z or 0),
            )
        if emission.anchor.entity_id is None:
            return None
        return positions.get(emission.anchor.entity_id)

    def _sound_confidence(
        self,
        origin: SpatialPosition,
        observer: SpatialPosition,
        emission: EventEmission,
        zones: dict[str, SpatialZone],
        portals: tuple[SpatialPortal, ...],
        occluders: tuple[SpatialOccluder, ...],
    ) -> tuple[float, tuple[str, ...]]:
        origin_zone, observer_zone = str(origin.zone_id), str(observer.zone_id)
        transmission = 1.0
        reasons = ["sound.same_zone"]
        if origin_zone != observer_zone:
            transmission = self._zone_transmission(
                origin_zone, observer_zone, portals, modality=SensoryModality.SOUND
            )
            if transmission <= 0:
                return 0.0, ()
            reasons = ["sound.portal_path"]
        distance = math.dist((origin.x, origin.y, origin.z), (observer.x, observer.y, observer.z))
        if origin_zone != observer_zone:
            # Crossing a zone boundary represents walls/room volume even when
            # local coordinates happen to share the same origin.
            distance = max(distance, 4.0)
        noise = zones.get(observer_zone, zones["world"]).ambient_noise
        attenuation = 1.0
        if origin_zone == observer_zone:
            line = set(self._supercover(origin.x, origin.y, observer.x, observer.y)[1:-1])
            for item in occluders:
                if str(item.zone_id) == origin_zone and (item.x, item.y) in line:
                    attenuation *= item.sound_attenuation
        effective_range = emission.max_range * emission.intensity * transmission * attenuation
        effective_range *= max(0.05, 1.0 - noise)
        if effective_range <= 0 or distance > effective_range:
            return 0.0, ()
        return max(0.05, 1.0 - distance / max(effective_range, 1.0)), tuple(reasons)

    def _sight_confidence(
        self,
        origin: SpatialPosition,
        observer: SpatialPosition,
        emission: EventEmission,
        zones: dict[str, SpatialZone],
        occluders: tuple[SpatialOccluder, ...],
    ) -> tuple[float, tuple[str, ...]]:
        zone = str(origin.zone_id)
        if zone != str(observer.zone_id):
            return 0.0, ()
        distance = math.dist((origin.x, origin.y, origin.z), (observer.x, observer.y, observer.z))
        light = zones.get(zone, zones["world"]).ambient_light
        effective_range = emission.max_range * max(0.05, light)
        if distance > effective_range:
            return 0.0, ()
        line = set(self._supercover(origin.x, origin.y, observer.x, observer.y)[1:-1])
        opacity = sum(
            item.sight_opacity
            for item in occluders
            if str(item.zone_id) == zone and (item.x, item.y) in line
        )
        if opacity >= 1:
            return 0.0, ()
        return max(0.05, (1.0 - distance / max(effective_range, 1.0)) * (1.0 - opacity)), (
            "sight.line_of_sight",
        )

    @staticmethod
    def _zone_transmission(
        start: str,
        goal: str,
        portals: tuple[SpatialPortal, ...],
        *,
        modality: SensoryModality,
    ) -> float:
        queue: deque[tuple[str, float]] = deque([(start, 1.0)])
        best = {start: 1.0}
        while queue:
            zone, strength = queue.popleft()
            for portal in portals:
                left, right = str(portal.from_zone_id), str(portal.to_zone_id)
                if zone not in {left, right}:
                    continue
                next_zone = right if zone == left else left
                base = (
                    portal.sound_transmission
                    if modality is SensoryModality.SOUND
                    else portal.sight_transmission
                )
                if portal.state in {"CLOSED", "LOCKED"}:
                    base *= 0.2
                candidate = strength * base
                if candidate <= best.get(next_zone, 0):
                    continue
                if next_zone == goal:
                    return candidate
                best[next_zone] = candidate
                queue.append((next_zone, candidate))
        return 0.0

    @staticmethod
    def _supercover(x0: int, y0: int, x1: int, y1: int) -> tuple[tuple[int, int], ...]:
        points: list[tuple[int, int]] = []
        dx, dy = x1 - x0, y1 - y0
        nx, ny = abs(dx), abs(dy)
        sign_x = 1 if dx > 0 else -1
        sign_y = 1 if dy > 0 else -1
        point_x, point_y = x0, y0
        ix = iy = 0
        points.append((point_x, point_y))
        while ix < nx or iy < ny:
            left = (1 + 2 * ix) * ny
            right = (1 + 2 * iy) * nx
            if left == right:
                point_x += sign_x
                point_y += sign_y
                ix += 1
                iy += 1
            elif left < right:
                point_x += sign_x
                ix += 1
            else:
                point_y += sign_y
                iy += 1
            points.append((point_x, point_y))
        return tuple(points)

"""Read-only acknowledgement of one actor's command and its frozen observation grant."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from cognition.perception import PerceptionEngine, PerceptionProfile
from cognition.store import MindStore
from kernel.application import SimulationApplication
from kernel.command_bus import CommandReceipt


class SceneRefreshCursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    world_id: uuid.UUID
    branch_id: uuid.UUID
    observer_entity_id: uuid.UUID
    event_id: uuid.UUID
    projection_version: int


class SceneRefreshStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID
    ready: bool
    observed: bool


def command_scene_cursor(
    receipt: CommandReceipt, projection_version: int
) -> SceneRefreshCursor | None:
    event = receipt.event
    if not receipt.result.accepted or event.embodied_entity_id is None:
        return None
    return SceneRefreshCursor(
        world_id=event.world_id,
        branch_id=event.branch_id,
        observer_entity_id=event.embodied_entity_id,
        event_id=event.event_id,
        projection_version=projection_version,
    )


def scene_refresh_status(
    simulation: SimulationApplication,
    minds: MindStore,
    *,
    world_id: uuid.UUID,
    branch_id: uuid.UUID,
    observer_entity_id: uuid.UUID,
    actor_id: uuid.UUID,
    after_event_id: uuid.UUID,
) -> SceneRefreshStatus:
    # Viewpoint access must already have been checked. A read-capable actor still cannot
    # use this receipt probe to discover another actor's commands or another body's history.
    event = simulation.events.get(after_event_id)
    if event is None:
        raise KeyError("scene refresh receipt not found")
    if (event.world_id, event.branch_id, event.embodied_entity_id, event.actor_id) != (
        world_id,
        branch_id,
        observer_entity_id,
        actor_id,
    ):
        raise PermissionError("scene refresh receipt is not available for this viewpoint")
    grant = simulation.perception_grant(after_event_id, observer_entity_id)
    expected = None
    if grant is not None:
        expected = PerceptionEngine().observe(
            event,
            PerceptionProfile(observer_entity_id=observer_entity_id, observer_actor_id=actor_id),
            grant=grant,
        )
    observed = expected is not None and minds.has_observation(
        expected.observation_id, branch_id=branch_id
    )
    return SceneRefreshStatus(
        event_id=after_event_id, ready=expected is None or observed, observed=observed
    )

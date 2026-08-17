from __future__ import annotations

import uuid
from typing import Any

from kernel.contracts import Actor, EventEnvelopeV2


class VisibilityPolicy:
    @staticmethod
    def event_for(event: EventEnvelopeV2, actor: Actor) -> EventEnvelopeV2 | None:
        if actor.actor_id in event.visible_to or "world.read.all" in actor.capabilities:
            return event
        return None

    @staticmethod
    def entity_for(
        public_state: dict[str, Any],
        secret_state: dict[str, Any],
        actor: Actor,
        controller_actor_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        visible = dict(public_state)
        if actor.actor_id == controller_actor_id or "entity.read.secret" in actor.capabilities:
            visible.update(secret_state)
        return visible

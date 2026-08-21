from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

from cognition.engine import SubjectiveStatePipeline
from cognition.perception import PerceptionProfile
from cognition.postgres import PostgresMindRepository
from cognition.store import MindStore
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant


@dataclass(frozen=True)
class ClaimedWorldEvent:
    outbox_id: int
    event: EventEnvelopeV2
    perceptions: tuple[PerceptionGrant, ...]


class WorldEventProjector:
    """Retry-safe outbox consumer for subjective observations, beliefs, and memories."""

    def __init__(self, dsn: str, *, worker_id: str | None = None) -> None:
        self.dsn = dsn
        self.worker_id = worker_id or f"world-events:{socket.gethostname()}:{os.getpid()}"
        self.repository = PostgresMindRepository(dsn)
        self.pipeline = SubjectiveStatePipeline()

    def run_once(self, *, limit: int = 20) -> int:
        claimed = self._claim(limit)
        for item in claimed:
            try:
                self._project(item)
            except Exception as exc:
                self._release(item.outbox_id, type(exc).__name__)
            else:
                self._complete(item.outbox_id)
        return len(claimed)

    def run_forever(self, *, idle_seconds: float = 0.5) -> None:
        while True:
            processed = self.run_once()
            if processed == 0:
                time.sleep(idle_seconds)

    def _claim(self, limit: int) -> tuple[ClaimedWorldEvent, ...]:
        with psycopg2.connect(self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, payload
                    FROM sim.outbox
                    WHERE published_at IS NULL
                      AND available_at <= now()
                      AND (claimed_at IS NULL OR claimed_at < now() - interval '5 minutes')
                      AND topic LIKE 'world.%%'
                    ORDER BY id
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
                if rows:
                    cursor.execute(
                        """UPDATE sim.outbox
                        SET claimed_at=now(), claimed_by=%s
                        WHERE id = ANY(%s)""",
                        (self.worker_id, [row["id"] for row in rows]),
                    )
        claimed: list[ClaimedWorldEvent] = []
        for row in rows:
            payload: dict[str, Any] = row["payload"]
            event_payload = payload.get("event", payload)
            grants_payload = payload.get("perceptions", ())
            claimed.append(
                ClaimedWorldEvent(
                    outbox_id=int(row["id"]),
                    event=EventEnvelopeV2.model_validate(event_payload),
                    perceptions=tuple(
                        PerceptionGrant.model_validate(grant) for grant in grants_payload
                    ),
                )
            )
        return tuple(claimed)

    def _project(self, item: ClaimedWorldEvent) -> None:
        for grant in item.perceptions:
            actor_id = grant.controller_actor_id or item.event.actor_id
            state, observations, relationships = self.repository.load_projection(
                world_id=item.event.world_id,
                branch_id=item.event.branch_id,
                entity_id=grant.observer_entity_id,
                actor_id=actor_id,
            )
            store = MindStore()
            store.restore(
                state,
                branch_id=item.event.branch_id,
                observations=observations,
                relationships=relationships,
            )
            update = self.pipeline.process(
                item.event,
                PerceptionProfile(
                    observer_entity_id=grant.observer_entity_id,
                    observer_actor_id=actor_id,
                ),
                grant=grant,
                existing_beliefs=state.beliefs,
            )
            if update.observation is None or store.has_observation(
                update.observation.observation_id, branch_id=item.event.branch_id
            ):
                continue
            projected = store.preview_subjective_update(
                grant.observer_entity_id,
                update,
                branch_id=item.event.branch_id,
            )
            self.repository.save_subjective_update(
                world_id=item.event.world_id,
                branch_id=item.event.branch_id,
                actor_id=actor_id,
                state=projected,
                update=update,
            )

    def _complete(self, outbox_id: int) -> None:
        with psycopg2.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE sim.outbox
                    SET published_at=now(), claimed_at=NULL, claimed_by=NULL, last_error=NULL
                    WHERE id=%s AND claimed_by=%s""",
                    (outbox_id, self.worker_id),
                )

    def _release(self, outbox_id: int, error_name: str) -> None:
        with psycopg2.connect(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE sim.outbox
                    SET attempts=attempts+1,
                        available_at=now() + make_interval(
                          secs => LEAST(300, power(2, attempts)::int)
                        ),
                        claimed_at=NULL, claimed_by=NULL, last_error=%s
                    WHERE id=%s AND claimed_by=%s""",
                    (error_name[:120], outbox_id, self.worker_id),
                )


def run_world_event_projector() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required for the world-event projector")
    WorldEventProjector(dsn).run_forever()

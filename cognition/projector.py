from __future__ import annotations

import os
import socket
import time
import uuid
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
    claim_owner: str = ""


class WorldEventProjector:
    """Retry-safe outbox consumer for subjective observations, beliefs, and memories."""

    def __init__(self, dsn: str, *, worker_id: str | None = None) -> None:
        self.dsn = dsn
        self.worker_id = worker_id or f"world-events:{socket.gethostname()}:{os.getpid()}"
        self.repository = PostgresMindRepository(dsn)
        self.pipeline = SubjectiveStatePipeline()

    def run_once(self, *, limit: int = 20, topic: str | None = None) -> int:
        count = 0
        while count < limit:
            claimed = self._claim(limit - count, topic=topic)
            if not claimed:
                break
            for item in claimed:
                self._process_claim(item)
            count += len(claimed)
        return count

    def run_forever(self, *, idle_seconds: float = 0.5) -> None:
        while True:
            processed = self.run_once()
            if processed == 0:
                time.sleep(idle_seconds)

    def _claim(self, limit: int, *, topic: str | None = None) -> tuple[ClaimedWorldEvent, ...]:
        claim_owner = f"{self.worker_id}:{uuid.uuid4()}"
        with psycopg2.connect(self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT work.id, work.payload
                    FROM sim.outbox work
                    WHERE work.published_at IS NULL
                      AND work.available_at <= now()
                      AND (work.claimed_at IS NULL
                           OR work.claimed_at < now() - interval '5 minutes')
                      AND work.topic LIKE 'world.%%'
                      AND (%s IS NULL OR work.topic=%s)
                      AND NOT EXISTS (
                        SELECT 1 FROM sim.outbox predecessor
                        WHERE predecessor.topic=work.topic AND predecessor.id < work.id
                          AND predecessor.published_at IS NULL
                      )
                    ORDER BY work.id
                    FOR UPDATE OF work SKIP LOCKED
                    LIMIT %s
                    """,
                    (topic, topic, limit),
                )
                rows = cursor.fetchall()
                if rows:
                    cursor.execute(
                        """UPDATE sim.outbox
                        SET claimed_at=now(), claimed_by=%s
                        WHERE id = ANY(%s)""",
                        (claim_owner, [row["id"] for row in rows]),
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
                    claim_owner=claim_owner,
                )
            )
        return tuple(claimed)

    def _process_claim(self, item: ClaimedWorldEvent) -> None:
        with psycopg2.connect(self.dsn) as connection, connection.cursor() as cursor:
            # Hold the row lock through projection. A replacement may reclaim
            # expired idle work, but cannot interleave with an already applying event.
            cursor.execute(
                """
                SELECT 1 FROM sim.outbox
                WHERE id=%s AND claimed_by=%s AND published_at IS NULL
                  AND claimed_at >= clock_timestamp() - interval '5 minutes'
                FOR UPDATE SKIP LOCKED
                """,
                (item.outbox_id, item.claim_owner),
            )
            if cursor.fetchone() is None:
                return
            try:
                self._project(item)
            except Exception as exc:
                cursor.execute(
                    """
                    UPDATE sim.outbox
                    SET attempts=attempts+1,
                        available_at=clock_timestamp() + make_interval(
                          secs => LEAST(300, power(2, LEAST(attempts, 9)))::int
                        ),
                        claimed_at=NULL, claimed_by=NULL, last_error=%s
                    WHERE id=%s
                    """,
                    (type(exc).__name__[:120], item.outbox_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE sim.outbox
                    SET published_at=clock_timestamp(), claimed_at=NULL,
                        claimed_by=NULL, last_error=NULL
                    WHERE id=%s
                    """,
                    (item.outbox_id,),
                )

    def _project(self, item: ClaimedWorldEvent) -> None:
        projection_actor: uuid.UUID | None = None
        for grant in item.perceptions:
            if grant.controller_actor_id is None and projection_actor is None:
                # Unowned witnesses need infrastructure projection authority, not
                # the speaker's character executor (which can access only its own mind).
                with psycopg2.connect(self.dsn) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT a.id FROM sim.actor_capabilities c JOIN sim.actors a "
                            "ON a.id=c.actor_id AND a.is_active WHERE c.world_id=%s "
                            "AND c.capability='mind.write.all' ORDER BY "
                            "CASE WHEN a.actor_kind='SYSTEM' THEN 0 ELSE 1 END,"
                            "a.created_at,a.id LIMIT 1",
                            (str(item.event.world_id),),
                        )
                        row = cursor.fetchone()
                        projection_actor = uuid.UUID(str(row[0])) if row else item.event.actor_id
            actor_id = grant.controller_actor_id or projection_actor or item.event.actor_id
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


def run_world_event_projector() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL is required for the world-event projector")
    WorldEventProjector(dsn).run_forever()

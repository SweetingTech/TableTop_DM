"""Private append-only human evidence, committed alongside its canonical source event."""

from __future__ import annotations

import uuid
from typing import Protocol

import psycopg2.extras

from cognition.behavior import HumanMovementEvidence
from kernel.control import ControlScope
from kernel.database import transaction


class BehaviorEvidenceReader(Protocol):
    def read(
        self, scope: ControlScope, actor_id: uuid.UUID
    ) -> tuple[tuple[uuid.UUID, HumanMovementEvidence], ...]: ...


class PostgresBehaviorEvidence:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def read(
        self, scope: ControlScope, actor_id: uuid.UUID
    ) -> tuple[tuple[uuid.UUID, HumanMovementEvidence], ...]:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT event_id,payload FROM cognition.human_movement_evidence "
                    "WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) "
                    "ORDER BY sequence DESC LIMIT 256",
                    tuple(map(str, scope.key)),
                )
                return tuple(
                    (
                        uuid.UUID(str(row["event_id"])),
                        HumanMovementEvidence.model_validate(row["payload"]),
                    )
                    for row in cursor.fetchall()
                )


def persist_human_evidence(cursor, event_id: uuid.UUID, evidence: dict) -> None:
    row = HumanMovementEvidence.model_validate(evidence)
    fields = (
        "world_id",
        "branch_id",
        "run_id",
        "entity_id",
        "player_actor_id",
        "character_id",
        "binding_id",
    )
    cursor.execute(
        "INSERT INTO cognition.human_movement_evidence "
        "(event_id,"
        + ",".join(fields)
        + ",payload) VALUES (%s,"
        + ",".join(["%s"] * len(fields))
        + ",%s::jsonb)",
        (str(event_id), *(str(getattr(row, name)) for name in fields), row.model_dump_json()),
    )

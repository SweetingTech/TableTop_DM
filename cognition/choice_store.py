from __future__ import annotations

import uuid

import psycopg2.extras

from cognition.behavior_store import persist_human_evidence
from cognition.choices import HumanChoiceEvidence
from kernel.control import ControlScope
from kernel.database import transaction


class PostgresChoiceEvidence:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def read(
        self, scope: ControlScope, actor_id: uuid.UUID
    ) -> tuple[tuple[uuid.UUID, HumanChoiceEvidence], ...]:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT event_id,payload FROM cognition.human_choice_evidence WHERE "
                    "(world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) "
                    "ORDER BY sequence DESC LIMIT 256",
                    tuple(map(str, scope.key)),
                )
                return tuple(
                    (
                        uuid.UUID(str(row["event_id"])),
                        HumanChoiceEvidence.model_validate(row["payload"]),
                    )
                    for row in cursor.fetchall()
                )


def persist_choice_bundle(cursor, event_id: uuid.UUID, bundle: dict) -> None:
    if "movement" not in bundle:
        persist_human_evidence(cursor, event_id, bundle)
        return
    if bundle.get("movement") is not None:
        persist_human_evidence(cursor, event_id, bundle["movement"])
    if bundle.get("choices") is None:
        return
    row = HumanChoiceEvidence.model_validate(bundle["choices"])
    cursor.execute(
        "INSERT INTO cognition.human_choice_evidence "
        "(event_id,world_id,branch_id,run_id,entity_id,player_actor_id,"
        "character_id,binding_id,payload) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (
            str(event_id),
            str(row.world_id),
            str(row.branch_id),
            str(row.run_id),
            str(row.entity_id),
            str(row.player_actor_id),
            str(row.character_id),
            str(row.binding_id),
            row.model_dump_json(),
        ),
    )

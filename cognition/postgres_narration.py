"""Actor-scoped retention of derived narration in PostgreSQL."""

from __future__ import annotations

import uuid

from psycopg2.errors import CheckViolation, InsufficientPrivilege
from psycopg2.extras import RealDictCursor, execute_values

from cognition.narration import NarrationEntry
from kernel.database import transaction

_FIELDS = (
    "narration_id",
    "world_id",
    "branch_id",
    "run_id",
    "audience",
    "observer_entity_id",
    "source_event_id",
    "source_observation_id",
    "occurred_at",
    "version",
    "text",
)
_COLUMNS = ", ".join(_FIELDS)


class PostgresNarrations:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def retain(
        self, entries: tuple[NarrationEntry, ...], *, actor_id: uuid.UUID
    ) -> tuple[NarrationEntry, ...]:
        if not entries:
            return ()
        keys = [str(entry.narration_id) for entry in entries]
        data = [entry.model_dump(mode="json") for entry in entries]
        rows = [tuple(item[field] for field in _FIELDS) + (str(actor_id),) for item in data]
        try:
            with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    execute_values(
                        cursor,
                        f"""INSERT INTO cognition.narration_entries ({_COLUMNS}, requester_actor_id)
                            VALUES %s ON CONFLICT (narration_id) DO NOTHING""",
                        rows,
                    )
                    cursor.execute(
                        f"SELECT {_COLUMNS} FROM cognition.narration_entries "
                        "WHERE narration_id = ANY(%s::uuid[])",
                        (keys,),
                    )
                    saved = {str(row["narration_id"]): row for row in cursor.fetchall()}
                    if len(saved) != len(set(keys)):
                        raise PermissionError("actor cannot retain this narration")
                    return tuple(NarrationEntry.model_validate(saved[key]) for key in keys)
        except InsufficientPrivilege:
            raise PermissionError("actor cannot retain this narration") from None
        except CheckViolation as error:
            if error.diag.constraint_name == "campaign_branch_archived":
                raise PermissionError("this continuation is archived") from None
            raise

    def get(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        narration_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
    ) -> NarrationEntry | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    f"SELECT {_COLUMNS} FROM cognition.narration_entries "
                    "WHERE (world_id, branch_id, narration_id) = (%s, %s, %s)",
                    (str(world_id), str(branch_id), str(narration_id)),
                )
                row = cursor.fetchone()
                return NarrationEntry.model_validate(row) if row is not None else None

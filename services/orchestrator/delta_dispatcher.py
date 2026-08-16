"""Registry-backed application of committed state deltas.

The orchestrator is allowed to mutate canonical state only after a proposal
has passed validation/auth/resource checks and the tool call has been written
to the ledger. This module keeps the table/operation dispatch explicit while
removing the hardcoded if/elif block from ``OrchestratorPipeline``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from shared.schemas.events import StateDelta


class UnsupportedStateDeltaError(ValueError):
    """Raised when a tool returns a delta with no registered applier."""


DeltaHandler = Callable[[StateDelta, Any], None]


class StateDeltaDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], DeltaHandler] = {}
        self.register("state.entities", "UPDATE", self._apply_entity_update)
        self.register("state.conditions", "INSERT", self._apply_condition_insert)
        self.register("state.conditions", "DELETE", self._apply_condition_delete)

    def register(self, table: str, operation: str, handler: DeltaHandler) -> None:
        self._handlers[(table, operation.upper())] = handler

    def apply(self, delta: StateDelta, conn: Any) -> None:
        key = (delta.table, delta.operation.upper())
        handler = self._handlers.get(key)
        if not handler:
            raise UnsupportedStateDeltaError(
                f"Unsupported state delta operation: {delta.table} {delta.operation}"
            )
        handler(delta, conn)

    def _apply_entity_update(self, delta: StateDelta, conn: Any) -> None:
        if not delta.entity_id:
            raise UnsupportedStateDeltaError("state.entities UPDATE requires entity_id")
        changes = delta.changes
        cur = conn.cursor()
        try:
            if "hp_current" in changes:
                cur.execute(
                    "UPDATE state.entities SET hp_current = %s, updated_at = now() WHERE id = %s",
                    (changes["hp_current"], str(delta.entity_id)),
                )

            has_x = "public_sheet_x" in changes
            has_y = "public_sheet_y" in changes
            if has_x and has_y:
                cur.execute(
                    """
                    UPDATE state.entities
                    SET public_sheet = jsonb_set(
                        jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{x}', %s::jsonb),
                        '{y}', %s::jsonb
                    ),
                    updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        json.dumps(changes["public_sheet_x"]),
                        json.dumps(changes["public_sheet_y"]),
                        str(delta.entity_id),
                    ),
                )
            elif has_x:
                cur.execute(
                    """
                    UPDATE state.entities
                    SET public_sheet = jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{x}', %s::jsonb),
                    updated_at = now()
                    WHERE id = %s
                    """,
                    (json.dumps(changes["public_sheet_x"]), str(delta.entity_id)),
                )
            elif has_y:
                cur.execute(
                    """
                    UPDATE state.entities
                    SET public_sheet = jsonb_set(COALESCE(public_sheet, '{}'::jsonb), '{y}', %s::jsonb),
                    updated_at = now()
                    WHERE id = %s
                    """,
                    (json.dumps(changes["public_sheet_y"]), str(delta.entity_id)),
                )
        finally:
            cur.close()

    def _apply_condition_insert(self, delta: StateDelta, conn: Any) -> None:
        if not delta.entity_id:
            raise UnsupportedStateDeltaError(
                "state.conditions INSERT requires entity_id"
            )
        changes = delta.changes
        cur = conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO state.conditions (entity_id, encounter_id, condition_type, duration_rounds, source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    str(delta.entity_id),
                    changes.get("encounter_id"),
                    changes.get("condition_type"),
                    changes.get("duration_rounds", -1),
                    changes.get("source", "unknown"),
                ),
            )
        finally:
            cur.close()

    def _apply_condition_delete(self, delta: StateDelta, conn: Any) -> None:
        if not delta.entity_id:
            raise UnsupportedStateDeltaError(
                "state.conditions DELETE requires entity_id"
            )
        changes = delta.changes
        cur = conn.cursor()
        try:
            cur.execute(
                "DELETE FROM state.conditions WHERE entity_id = %s AND condition_type = %s",
                (str(delta.entity_id), changes.get("condition_type")),
            )
        finally:
            cur.close()

# ruff: noqa: E501 -- SQL statements retain one-to-one column/value alignment.
"""Version-pinned controller configuration, separate from world truth and control grants."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from typing import Literal, Protocol

import psycopg2.extras
from pydantic import BaseModel, ConfigDict

from kernel.database import transaction


class CharacterBinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    binding_id: uuid.UUID
    character_id: uuid.UUID
    card_revision_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    persona_id: uuid.UUID
    persona_version_id: uuid.UUID
    compiler_version: str
    purpose: Literal["CHARACTER"] = "CHARACTER"
    replaces_binding_id: uuid.UUID | None = None
    recorded_by: uuid.UUID
    recorded_at: datetime

    @property
    def scope(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        return self.world_id, self.branch_id, self.run_id, self.entity_id


class CharacterBindingRepository(Protocol):
    def latest(
        self, scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID], *, actor_id: uuid.UUID
    ) -> CharacterBinding | None: ...
    def save(self, binding: CharacterBinding, *, actor_id: uuid.UUID) -> CharacterBinding: ...


class InMemoryCharacterBindings:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, CharacterBinding] = {}
        self._lock = threading.RLock()

    def latest(
        self, scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID], *, actor_id: uuid.UUID
    ) -> CharacterBinding | None:
        with self._lock:
            return next(
                (row for row in reversed(tuple(self.rows.values())) if row.scope == scope), None
            )

    def save(self, binding: CharacterBinding, *, actor_id: uuid.UUID) -> CharacterBinding:
        with self._lock:
            existing = self.rows.get(binding.binding_id)
            if existing is not None:
                _check_retry(existing, binding)
                return existing
            current = self.latest(binding.scope, actor_id=actor_id)
            if (current.binding_id if current else None) != binding.replaces_binding_id:
                raise ValueError("character binding changed; reload before replacing it")
            if current and current.character_id != binding.character_id:
                raise ValueError("body already represents another character")
            self.rows[binding.binding_id] = binding
            return binding


class PostgresCharacterBindings:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def latest(
        self, scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID], *, actor_id: uuid.UUID
    ) -> CharacterBinding | None:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT * FROM tabletop.character_bindings WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s) ORDER BY sequence DESC LIMIT 1",
                    tuple(map(str, scope)),
                )
                row = cursor.fetchone()
                return CharacterBinding.model_validate(dict(row)) if row else None

    def save(self, binding: CharacterBinding, *, actor_id: uuid.UUID) -> CharacterBinding:
        try:
            return self._save(binding, actor_id=actor_id)
        except psycopg2.errors.InsufficientPrivilege:
            raise PermissionError("actor cannot save this character binding") from None
        except psycopg2.Error:
            raise ValueError(
                "character binding changed or references unavailable data; reload before retrying"
            ) from None

    def _save(self, binding: CharacterBinding, *, actor_id: uuid.UUID) -> CharacterBinding:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    "SELECT id FROM sim.runs WHERE (world_id,branch_id,id)=(%s,%s,%s) FOR UPDATE",
                    tuple(map(str, binding.scope[:3])),
                )
                if cursor.fetchone() is None:
                    raise ValueError("binding run is unavailable")
                cursor.execute(
                    "SELECT * FROM tabletop.character_bindings WHERE binding_id=%s",
                    (str(binding.binding_id),),
                )
                previous = cursor.fetchone()
                if previous:
                    existing = CharacterBinding.model_validate(dict(previous))
                    _check_retry(existing, binding)
                    return existing
                # Initialize only a missing neutral mind. Rebinding never replaces experience,
                # goals, beliefs, relationships, or a separate human/runtime assignment.
                cursor.execute(
                    "INSERT INTO cognition.mind_states(world_id,branch_id,entity_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    tuple(map(str, (binding.world_id, binding.branch_id, binding.entity_id))),
                )
                fields = tuple(CharacterBinding.model_fields)
                values = binding.model_dump(mode="json")
                cursor.execute(
                    "INSERT INTO tabletop.character_bindings ("
                    + ",".join(fields)
                    + ") VALUES ("
                    + ",".join(["%s"] * len(fields))
                    + ") RETURNING *",
                    tuple(values[name] for name in fields),
                )
                stored = cursor.fetchone()
                if stored is None:
                    raise RuntimeError("character binding was not returned")
                return CharacterBinding.model_validate(dict(stored))


def _check_retry(existing: CharacterBinding, requested: CharacterBinding) -> None:
    excluded = {"recorded_at", "recorded_by"}
    if existing.model_dump(exclude=excluded) != requested.model_dump(exclude=excluded):
        raise ValueError("character binding retry differs from the original request")


def new_binding(
    *,
    character_id: uuid.UUID,
    card_revision_id: uuid.UUID,
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID],
    persona_id: uuid.UUID,
    persona_version_id: uuid.UUID,
    compiler_version: str,
    actor_id: uuid.UUID,
    replaces_binding_id: uuid.UUID | None,
) -> CharacterBinding:
    identity = ":".join(
        map(
            str,
            (
                *scope,
                character_id,
                card_revision_id,
                persona_id,
                persona_version_id,
                compiler_version,
                replaces_binding_id,
            ),
        )
    )
    return CharacterBinding(
        binding_id=uuid.uuid5(uuid.NAMESPACE_URL, "tabletop-dm:character-binding:" + identity),
        character_id=character_id,
        card_revision_id=card_revision_id,
        world_id=scope[0],
        branch_id=scope[1],
        run_id=scope[2],
        entity_id=scope[3],
        persona_id=persona_id,
        persona_version_id=persona_version_id,
        compiler_version=compiler_version,
        replaces_binding_id=replaces_binding_id,
        recorded_by=actor_id,
        recorded_at=datetime.now(UTC),
    )

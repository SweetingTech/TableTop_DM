from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import url2pathname

import psycopg2.extras

from kernel.database import transaction
from persona.models import PersonaVersionRecord
from population.lifecycle import PopulationLifecycle
from population.models import (
    PopulationLevel,
    PopulationMember,
    PopulationTransition,
)


class PostgresPopulationRepository:
    """Metadata catalog for immutable Parquet pools and materialized people."""

    GENERATOR_VERSION = "persona-gen-0.4"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def save_pool(
        self,
        *,
        population_id: uuid.UUID,
        name: str,
        size: int,
        seed: int,
        schema_version: str,
        path: Path,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
    ) -> dict[str, Any]:
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        artifact_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"tabletop-dm:population-artifact:{content_hash}"
        )
        pool_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:population-pool:{population_id}:{content_hash}",
        )
        uri = path.resolve().as_uri()
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO artifacts.objects (
                      id, artifact_kind, uri, content_hash, media_type,
                      byte_size, metadata
                    ) VALUES (%s,'PERSONA_POOL',%s,%s,'application/vnd.apache.parquet',
                              %s,%s::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(artifact_id),
                        uri,
                        content_hash,
                        path.stat().st_size,
                        json.dumps({"population_id": str(population_id), "name": name}),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO population.definitions (
                      id, population_key, version, schema_version, world_id, branch_id,
                      distributions, target_size, seed
                    ) VALUES (%s,%s,%s,%s,%s,%s,'{}'::jsonb,%s,%s)
                    ON CONFLICT (population_key, version) DO NOTHING
                    """,
                    (
                        str(population_id),
                        name,
                        f"seed-{seed}-n{size}",
                        schema_version,
                        str(world_id),
                        str(branch_id),
                        size,
                        seed,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO population.pools (
                      id, definition_id, artifact_id, row_count,
                      generator_version, state, completed_at
                    ) VALUES (%s,%s,%s,%s,%s,'READY',now())
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (
                        str(pool_id),
                        str(population_id),
                        str(artifact_id),
                        size,
                        self.GENERATOR_VERSION,
                    ),
                )
        return {
            "population_id": str(population_id),
            "name": name,
            "size": size,
            "seed": seed,
            "artifact": str(path.resolve()),
            "status": "READY",
            "schema_version": schema_version,
            "world_id": str(world_id),
            "branch_id": str(branch_id),
            "materialized": 0,
            "active": 0,
            "dimensions": {},
            "_materialized_ids": [],
            "_active_ids": [],
        }

    def list_pools(self) -> tuple[dict[str, Any], ...]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT definition.id, definition.population_key,
                           definition.schema_version, definition.target_size,
                           definition.seed, definition.world_id,
                           definition.branch_id, pool.state, artifact.uri,
                           count(person.id) AS materialized,
                           count(person.id) FILTER (
                             WHERE person.activation_state = 'ACTIVE'
                           ) AS active,
                           array_remove(array_agg(person.persona_id::text), NULL)
                             AS materialized_ids,
                           array_remove(array_agg(person.persona_id::text) FILTER (
                             WHERE person.activation_state = 'ACTIVE'
                           ), NULL) AS active_ids
                    FROM population.definitions definition
                    JOIN population.pools pool ON pool.definition_id = definition.id
                    JOIN artifacts.objects artifact ON artifact.id = pool.artifact_id
                    LEFT JOIN population.materialized_people person
                      ON person.population_id = definition.id
                    WHERE pool.state = 'READY'
                    GROUP BY definition.id, definition.population_key,
                             definition.schema_version, definition.target_size,
                             definition.seed, definition.world_id,
                             definition.branch_id, pool.state, artifact.uri,
                             pool.created_at
                    ORDER BY pool.created_at
                    """
                )
                rows = list(cursor.fetchall())
        records = []
        for row in rows:
            uri = str(row["uri"])
            raw_path = url2pathname(urlparse(uri).path)
            if os.name == "nt" and len(raw_path) > 2 and raw_path[0] in "/\\":
                raw_path = raw_path[1:]
            path = Path(raw_path)
            records.append(
                {
                    "population_id": str(row["id"]),
                    "name": row["population_key"],
                    "size": int(row["target_size"]),
                    "seed": int(row["seed"]),
                    "artifact": str(path),
                    "status": row["state"],
                    "schema_version": row["schema_version"],
                    "world_id": str(row["world_id"]),
                    "branch_id": str(row["branch_id"]),
                    "materialized": int(row["materialized"]),
                    "active": int(row["active"]),
                    "dimensions": {},
                    "_materialized_ids": list(row["materialized_ids"] or ()),
                    "_active_ids": list(row["active_ids"] or ()),
                }
            )
        return tuple(records)

    def save_materialized(
        self,
        *,
        population_id: uuid.UUID,
        version: PersonaVersionRecord,
        member: PopulationMember,
        transition: PopulationTransition,
    ) -> None:
        if member.world_id is None or member.branch_id is None:
            raise ValueError("durable population members require a world and branch")
        if member.persona_id != version.blueprint.persona_id:
            raise ValueError("member and persona version identities do not match")
        if transition.persona_id != member.persona_id:
            raise ValueError("transition and member identities do not match")
        identity = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:materialized:{population_id}:{member.world_id}:"
            f"{member.branch_id}:{member.persona_id}",
        )
        occupation = version.blueprint.dimensions.get("occupation_sector")
        finances = member.persistent_state.get("finances", {})
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO population.materialized_people (
                      id, population_id, world_id, branch_id, persona_id,
                      persona_version_id, occupation, finances, persistent_state,
                      active_state, compressed_state, activation_state,
                      lifecycle_version, world_step
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,
                      %s::jsonb,'MATERIALIZED',%s,%s
                    )
                    ON CONFLICT (population_id, persona_id) DO NOTHING
                    """,
                    (
                        str(identity),
                        str(population_id),
                        str(member.world_id),
                        str(member.branch_id),
                        str(member.persona_id),
                        str(version.version_id),
                        str(occupation) if occupation is not None else None,
                        json.dumps(finances),
                        json.dumps(member.persistent_state),
                        json.dumps(member.active_state),
                        json.dumps(member.compressed_state),
                        member.version,
                        member.world_step,
                    ),
                )
                if cursor.rowcount != 1:
                    cursor.execute(
                        """
                        SELECT world_id, branch_id, persona_version_id,
                               persistent_state, active_state, compressed_state,
                               lifecycle_version, world_step
                        FROM population.materialized_people
                        WHERE population_id=%s AND persona_id=%s
                        """,
                        (str(population_id), str(member.persona_id)),
                    )
                    existing = cursor.fetchone()
                    expected = (
                        member.world_id,
                        member.branch_id,
                        version.version_id,
                        member.persistent_state,
                        member.active_state,
                        member.compressed_state,
                        member.version,
                        member.world_step,
                    )
                    if existing != expected:
                        raise ValueError("materialized population member already differs")
                self._insert_transition(cursor, population_id, transition)

    def save_transition(
        self,
        *,
        population_id: uuid.UUID,
        member: PopulationMember,
        transition: PopulationTransition,
        activation_state: str,
    ) -> None:
        if member.world_id is None or member.branch_id is None:
            raise ValueError("durable population members require a world and branch")
        if activation_state not in {"MATERIALIZED", "ACTIVE", "COMPRESSED", "ARCHIVED"}:
            raise ValueError("invalid durable activation state")
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE population.materialized_people
                    SET persistent_state=%s::jsonb, active_state=%s::jsonb,
                        compressed_state=%s::jsonb, activation_state=%s,
                        finances=%s::jsonb, lifecycle_version=%s,
                        world_step=%s, updated_at=now()
                    WHERE population_id=%s AND world_id=%s AND branch_id=%s
                      AND persona_id=%s
                      AND lifecycle_version=%s
                      AND world_step <= %s
                    """,
                    (
                        json.dumps(member.persistent_state),
                        json.dumps(member.active_state),
                        json.dumps(member.compressed_state),
                        activation_state,
                        json.dumps(member.persistent_state.get("finances", {})),
                        member.version,
                        member.world_step,
                        str(population_id),
                        str(member.world_id),
                        str(member.branch_id),
                        str(member.persona_id),
                        member.version - 1,
                        member.world_step,
                    ),
                )
                if cursor.rowcount != 1:
                    cursor.execute(
                        """
                        SELECT persistent_state, active_state, compressed_state,
                               activation_state, lifecycle_version, world_step
                        FROM population.materialized_people
                        WHERE population_id=%s AND world_id=%s AND branch_id=%s
                          AND persona_id=%s
                        """,
                        (
                            str(population_id),
                            str(member.world_id),
                            str(member.branch_id),
                            str(member.persona_id),
                        ),
                    )
                    existing = cursor.fetchone()
                    expected = (
                        member.persistent_state,
                        member.active_state,
                        member.compressed_state,
                        activation_state,
                        member.version,
                        member.world_step,
                    )
                    if existing is None:
                        raise KeyError(member.persona_id)
                    if existing != expected:
                        raise ValueError("population lifecycle version or world step conflict")
                self._insert_transition(cursor, population_id, transition)

    def load_lifecycle(self, population_id: uuid.UUID) -> PopulationLifecycle:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT world_id, branch_id
                    FROM population.definitions
                    WHERE id=%s
                    """,
                    (str(population_id),),
                )
                target = cursor.fetchone()
                if target is None:
                    raise KeyError(population_id)
                world_id = uuid.UUID(str(target["world_id"]))
                branch_id = uuid.UUID(str(target["branch_id"]))
                cursor.execute(
                    """
                    SELECT person.*, blueprint.dimensions
                    FROM population.materialized_people person
                    JOIN persona.blueprints blueprint
                      ON blueprint.persona_id = person.persona_id
                     AND blueprint.version_id = person.persona_version_id
                    WHERE person.population_id=%s
                    ORDER BY person.created_at, person.persona_id
                    """,
                    (str(population_id),),
                )
                members = [
                    PopulationMember(
                        persona_id=uuid.UUID(str(row["persona_id"])),
                        level=(
                            PopulationLevel.ACTIVE
                            if row["activation_state"] == "ACTIVE"
                            else PopulationLevel.MATERIALIZED
                        ),
                        world_id=uuid.UUID(str(row["world_id"])),
                        branch_id=uuid.UUID(str(row["branch_id"])),
                        profile=dict(row["dimensions"]),
                        persistent_state=dict(row["persistent_state"]),
                        active_state=dict(row["active_state"]),
                        compressed_state=dict(row["compressed_state"]),
                        version=int(row["lifecycle_version"]),
                        world_step=int(row["world_step"]),
                    )
                    for row in cursor.fetchall()
                ]
                cursor.execute(
                    """
                    SELECT * FROM population.lifecycle_transitions
                    WHERE population_id=%s
                    ORDER BY sequence, created_at, transition_id
                    """,
                    (str(population_id),),
                )
                transitions = [
                    PopulationTransition(
                        transition_id=uuid.UUID(str(row["transition_id"])),
                        sequence=int(row["sequence"]),
                        persona_id=uuid.UUID(str(row["persona_id"])),
                        world_id=uuid.UUID(str(row["world_id"])),
                        branch_id=uuid.UUID(str(row["branch_id"])),
                        lifecycle_version=int(row["lifecycle_version"]),
                        from_level=PopulationLevel(row["from_level"]),
                        to_level=PopulationLevel(row["to_level"]),
                        reason=row["reason"],
                        world_step=int(row["world_step"]),
                        persistent_state_hash=row["persistent_state_hash"],
                        active_state_hash=row["active_state_hash"],
                    )
                    for row in cursor.fetchall()
                ]
        lifecycle = PopulationLifecycle(world_id, branch_id)
        lifecycle.restore(members, transitions)
        return lifecycle

    @staticmethod
    def _insert_transition(
        cursor: Any,
        population_id: uuid.UUID,
        transition: PopulationTransition,
    ) -> None:
        if transition.world_id is None or transition.branch_id is None:
            raise ValueError("durable transitions require a world and branch")
        cursor.execute(
            """
            INSERT INTO population.lifecycle_transitions (
              transition_id, population_id, world_id, branch_id, persona_id,
              sequence, lifecycle_version, from_level, to_level, reason,
              world_step, persistent_state_hash, active_state_hash
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (transition_id) DO NOTHING
            """,
            (
                str(transition.transition_id),
                str(population_id),
                str(transition.world_id),
                str(transition.branch_id),
                str(transition.persona_id),
                transition.sequence,
                transition.lifecycle_version,
                transition.from_level.value,
                transition.to_level.value,
                transition.reason,
                transition.world_step,
                transition.persistent_state_hash,
                transition.active_state_hash,
            ),
        )

    def member_state(
        self,
        *,
        population_id: uuid.UUID,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        persona_id: uuid.UUID,
    ) -> dict[str, Any]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT * FROM population.materialized_people
                    WHERE population_id=%s AND world_id=%s AND branch_id=%s
                      AND persona_id=%s
                    """,
                    (
                        str(population_id),
                        str(world_id),
                        str(branch_id),
                        str(persona_id),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise KeyError(persona_id)
                return dict(row)

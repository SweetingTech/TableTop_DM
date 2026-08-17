from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import psycopg2.extras

from kernel.database import transaction
from persona.models import (
    CompiledPersona,
    PersonaBlueprint,
    PersonaVersionRecord,
)
from persona.registry import PersonaSchemaRegistry


class PostgresPersonaRepository:
    """Append-only persistence for schema and persona identity versions."""

    def __init__(self, dsn: str, registry: PersonaSchemaRegistry) -> None:
        self.dsn = dsn
        self.registry = registry

    def sync_schema(self) -> None:
        definition = {
            "domain_packs": {
                name: value.model_dump(mode="json")
                for name, value in sorted(self.registry.domain_packs.items())
            },
            "dimensions": [
                value.model_dump(mode="json") for value in self.registry.ordered_dimensions()
            ],
            "constraints": [value.model_dump(mode="json") for value in self.registry.constraints],
        }
        encoded = json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()
        schema_hash = hashlib.sha256(encoded).hexdigest()
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO persona.schema_versions (
                      version, schema_hash, definition, status
                    ) VALUES (%s,%s,%s::jsonb,'ACTIVE')
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (self.registry.VERSION, schema_hash, json.dumps(definition)),
                )
                cursor.execute(
                    """
                    SELECT schema_hash FROM persona.schema_versions WHERE version = %s
                    """,
                    (self.registry.VERSION,),
                )
                row = cursor.fetchone()
                if row is None or str(row[0]) != schema_hash:
                    raise ValueError("persona schema version already exists with different content")

    def save_version(self, record: PersonaVersionRecord) -> PersonaVersionRecord:
        blueprint = record.blueprint
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO persona.blueprints (
                      persona_id, version_id, parent_version_id, schema_version,
                      seed, generator_version, source, content_hash, dimensions,
                      derived_traits, provenance, validation, created_at
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,
                      %s::jsonb,%s
                    )
                    ON CONFLICT (persona_id, content_hash) DO NOTHING
                    """,
                    (
                        str(blueprint.persona_id),
                        str(record.version_id),
                        str(record.parent_version_id) if record.parent_version_id else None,
                        blueprint.schema_version,
                        blueprint.seed,
                        blueprint.generator_version,
                        blueprint.source,
                        record.content_hash,
                        json.dumps(blueprint.dimensions, default=str),
                        json.dumps(blueprint.derived_traits, default=str),
                        json.dumps(
                            {
                                name: value.model_dump(mode="json")
                                for name, value in blueprint.provenance.items()
                            },
                            default=str,
                        ),
                        blueprint.validation.model_dump_json(),
                        record.created_at,
                    ),
                )
                cursor.execute(
                    """
                    SELECT version_id FROM persona.blueprints
                    WHERE persona_id = %s AND content_hash = %s
                    """,
                    (str(blueprint.persona_id), record.content_hash),
                )
                stored = cursor.fetchone()
                if stored is None or uuid.UUID(str(stored[0])) != record.version_id:
                    raise ValueError("stored persona version identity differs")
        return record

    def save_compiled(self, compiled: CompiledPersona) -> CompiledPersona:
        version_id = uuid.UUID(compiled.persona_version)
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO persona.compiled_profiles (
                      persona_id, persona_version_id, compiler_version,
                      identity_summary, policy_weights, starting_goals,
                      starting_beliefs, starting_relationships, routine_templates,
                      capability_modifiers, retrieval_filters
                    ) VALUES (
                      %s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,
                      %s::jsonb,%s::jsonb,%s::jsonb
                    ) ON CONFLICT DO NOTHING
                    """,
                    (
                        str(compiled.persona_id),
                        str(version_id),
                        compiled.compiler_version,
                        compiled.identity_summary,
                        json.dumps(compiled.policy_weights),
                        json.dumps(compiled.starting_goals),
                        json.dumps(compiled.starting_beliefs, default=str),
                        json.dumps(compiled.starting_relationships, default=str),
                        json.dumps(compiled.routines, default=str),
                        json.dumps(compiled.capability_modifiers),
                        json.dumps({"filters": compiled.retrieval_filters}),
                    ),
                )
        return compiled

    def list_versions(self) -> tuple[PersonaVersionRecord, ...]:
        with transaction(dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT persona_id, version_id, parent_version_id,
                           schema_version, seed, generator_version, source,
                           content_hash, dimensions, derived_traits, provenance,
                           validation, created_at
                    FROM persona.blueprints
                    ORDER BY created_at, persona_id, version_id
                    """
                )
                rows: list[dict[str, Any]] = list(cursor.fetchall())
        return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: dict[str, Any]) -> PersonaVersionRecord:
        blueprint = PersonaBlueprint.model_validate(
            {
                "persona_id": row["persona_id"],
                "schema_version": row["schema_version"],
                "seed": row["seed"],
                "generator_version": row["generator_version"],
                "source": row["source"],
                "dimensions": row["dimensions"],
                "derived_traits": row["derived_traits"],
                "provenance": row["provenance"],
                "validation": row["validation"],
            }
        )
        return PersonaVersionRecord(
            version_id=row["version_id"],
            blueprint=blueprint,
            content_hash=row["content_hash"],
            parent_version_id=row["parent_version_id"],
            created_at=row["created_at"],
        )

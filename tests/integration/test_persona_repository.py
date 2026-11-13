from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import make_dsn

from infra.migrate import migrate
from persona.compilation.compiler import PersonaCompiler
from persona.generation.generator import PersonaGenerator
from persona.models import PersonaPurpose
from persona.postgres import PostgresPersonaRepository
from persona.registry import PersonaSchemaRegistry
from persona.versioning import PersonaVersioning

pytestmark = pytest.mark.integration


class _IntegrationPersonaRegistry(PersonaSchemaRegistry):
    VERSION = "2.0.0-integration"


def test_persona_versions_and_compiled_profile_survive_reload(integration_stack) -> None:
    registry = _IntegrationPersonaRegistry.load_default()
    repository = PostgresPersonaRepository(integration_stack.database_url, registry)
    repository.sync_schema()
    risk = registry.dimensions["risk_tolerance"]
    alternate_default = "LOW" if risk.default != "LOW" else "HIGH"
    conflicting_registry = _IntegrationPersonaRegistry(
        {
            **registry.dimensions,
            "risk_tolerance": risk.model_copy(update={"default": alternate_default}),
        },
        registry.constraints,
        registry.domain_packs,
    )
    with pytest.raises(ValueError, match="same version|different content"):
        PostgresPersonaRepository(
            integration_stack.database_url,
            conflicting_registry,
        ).sync_schema()

    generated = PersonaGenerator(registry)
    first_blueprint = generated.generate(4815162342, {"risk_tolerance": "LOW"})
    second_blueprint = generated.generate(4815162342, {"risk_tolerance": "HIGH"}).model_copy(
        update={"persona_id": first_blueprint.persona_id}
    )
    first = PersonaVersioning.record(first_blueprint)
    second = PersonaVersioning.record(second_blueprint, parent_version_id=first.version_id)

    repository.save_version(first)
    repository.save_version(second)
    reloaded = repository.list_versions()
    matching = [
        item for item in reloaded if item.blueprint.persona_id == first_blueprint.persona_id
    ]

    by_version = {item.version_id: item for item in matching}
    assert set(by_version) == {first.version_id, second.version_id}
    assert by_version[second.version_id].parent_version_id == first.version_id
    assert (
        by_version[first.version_id].blueprint.schema_version
        == by_version[second.version_id].blueprint.schema_version
    )
    assert by_version[first.version_id].blueprint.dimensions["risk_tolerance"] == "LOW"
    assert by_version[second.version_id].blueprint.dimensions["risk_tolerance"] == "HIGH"

    compiled = PersonaCompiler().compile(
        second_blueprint,
        persona_version=str(second.version_id),
    )
    repository.save_compiled(compiled)

    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT identity_summary, policy_weights, retrieval_filters
            FROM persona.compiled_profiles
            WHERE persona_id = %s AND persona_version_id = %s
              AND compiler_version = %s
            """,
            (
                str(first_blueprint.persona_id),
                str(second.version_id),
                compiled.compiler_version,
            ),
        )
        stored = cursor.fetchone()
    assert stored is not None
    assert stored[0] == compiled.identity_summary
    assert stored[1] == compiled.policy_weights
    assert stored[2] == {"filters": list(compiled.retrieval_filters)}


@pytest.mark.parametrize(
    "updates",
    [
        {"identity_summary": "Changed identity"},
        {"policy_weights": {"risk": 0.42}},
        {"starting_goals": ("Changed goal",)},
        {"starting_beliefs": ({"known": "Changed belief"},)},
        {"starting_relationships": ({"trust": 0.5},)},
        {"routines": ({"activity": "Changed routine"},)},
        {"capability_modifiers": {"changed": 1.0}},
        {"retrieval_filters": ("Changed filter",)},
    ],
)
def test_compiled_profile_retry_rejects_changed_persisted_content(integration_stack, updates):
    registry = _IntegrationPersonaRegistry.load_default()
    repository = PostgresPersonaRepository(integration_stack.database_url, registry)
    repository.sync_schema()
    blueprint = PersonaGenerator(registry).generate(997, purpose=PersonaPurpose.CHARACTER)
    version = PersonaVersioning.record(blueprint)
    repository.save_version(version)
    compiled = PersonaCompiler().compile(blueprint, persona_version=str(version.version_id))
    assert repository.save_compiled(compiled) == compiled
    assert repository.save_compiled(compiled) == compiled
    with pytest.raises(ValueError, match="profile content differs"):
        repository.save_compiled(compiled.model_copy(update=updates))
    # A conflict must neither replace the original immutable row nor poison the next transaction.
    assert repository.save_compiled(compiled) == compiled


def test_character_purpose_survives_reload_and_rejects_mismatched_profiles(integration_stack):
    registry = _IntegrationPersonaRegistry.load_default()
    repository = PostgresPersonaRepository(integration_stack.database_url, registry)
    repository.sync_schema()
    generator = PersonaGenerator(registry)
    blueprints = [generator.generate(314, purpose=purpose) for purpose in PersonaPurpose]
    records = [PersonaVersioning.record(blueprint) for blueprint in blueprints]
    for record in records:
        repository.save_version(record)
    reloaded = PostgresPersonaRepository(integration_stack.database_url, registry).list_versions()
    by_id = {record.version_id: record for record in reloaded}
    for record in records:
        assert by_id[record.version_id] == record
        assert (
            PersonaVersioning.record(by_id[record.version_id].blueprint).content_hash
            == record.content_hash
        )

    character = next(
        record for record in records if record.blueprint.purpose == PersonaPurpose.CHARACTER
    )
    compiled = PersonaCompiler().compile(
        character.blueprint, persona_version=str(character.version_id)
    )
    wrong = compiled.model_copy(update={"purpose": PersonaPurpose.SIMULATED_PLAYTESTER})
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        repository.save_compiled(wrong)
    # The failed transaction leaves no profile behind and does not poison subsequent writes.
    repository.save_compiled(compiled)
    repository.save_compiled(compiled)
    with pytest.raises(ValueError, match="profile purpose differs"):
        repository.save_compiled(wrong)
    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT purpose FROM persona.compiled_profiles "
            "WHERE persona_id = %s AND persona_version_id = %s",
            (str(compiled.persona_id), compiled.persona_version),
        )
        assert cursor.fetchall() == [("CHARACTER",)]
        cursor.execute(
            "SELECT purpose FROM persona.blueprints WHERE version_id = %s",
            (compiled.persona_version,),
        )
        assert cursor.fetchone() == ("CHARACTER",)

    for table in ("blueprints", "compiled_profiles"):
        with pytest.raises(psycopg2.Error, match="append-only"):
            with (
                psycopg2.connect(integration_stack.admin_url) as connection,
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    sql.SQL(
                        "UPDATE persona.{} SET purpose = 'SIMULATED_PLAYTESTER' "
                        "WHERE persona_id = %s"
                    ).format(sql.Identifier(table)),
                    (str(compiled.persona_id),),
                )

    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO persona.blueprints (persona_id, version_id, schema_version, seed,
                  generator_version, source, content_hash, dimensions, validation, purpose)
                VALUES (%s,%s,%s,1,'test','manual',%s,'{}','{}','INVALID')
                """,
                (str(uuid.uuid4()), str(uuid.uuid4()), registry.VERSION, "a" * 64),
            )
    with pytest.raises(psycopg2.errors.CheckViolation):
        with (
            psycopg2.connect(integration_stack.database_url) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute(
                """
                INSERT INTO persona.compiled_profiles (persona_id, persona_version_id,
                  compiler_version, identity_summary, policy_weights, starting_goals,
                  retrieval_filters, purpose)
                VALUES (%s,%s,'invalid-purpose','test','{}','[]','{}','INVALID')
                """,
                (str(compiled.persona_id), compiled.persona_version),
            )


def test_purpose_upgrade_preserves_legacy_versions_and_compiled_profiles(
    integration_stack, tmp_path
):
    database_name = f"ttdm_purpose_upgrade_{uuid.uuid4().hex}"
    upgrade_url = make_dsn(integration_stack.admin_url, dbname=database_name)
    maintenance = psycopg2.connect(integration_stack.admin_url)
    maintenance.autocommit = True
    try:
        with maintenance.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        migrations = Path(__file__).resolve().parents[2] / "infra/sql/migrations"
        prior = tmp_path / "prior"
        prior.mkdir()
        for path in sorted(migrations.glob("*.sql"))[:3]:
            shutil.copy2(path, prior / path.name)
        migrate(upgrade_url, prior)
        registry = _IntegrationPersonaRegistry.load_default()
        PostgresPersonaRepository(upgrade_url, registry).sync_schema()
        record = PersonaVersioning.record(PersonaGenerator(registry).generate(2718))
        blueprint = record.blueprint
        with psycopg2.connect(upgrade_url) as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO persona.blueprints (persona_id,version_id,schema_version,seed,
                  generator_version,source,content_hash,dimensions,derived_traits,provenance,
                  validation,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s)
                """,
                (
                    str(blueprint.persona_id),
                    str(record.version_id),
                    blueprint.schema_version,
                    blueprint.seed,
                    blueprint.generator_version,
                    blueprint.source,
                    record.content_hash,
                    json.dumps(blueprint.dimensions),
                    json.dumps(blueprint.derived_traits),
                    json.dumps(
                        {
                            name: value.model_dump(mode="json")
                            for name, value in blueprint.provenance.items()
                        }
                    ),
                    blueprint.validation.model_dump_json(),
                    record.created_at,
                ),
            )
            cursor.execute(
                """
                INSERT INTO persona.compiled_profiles (persona_id,persona_version_id,
                  compiler_version,identity_summary,policy_weights,starting_goals,retrieval_filters)
                VALUES (%s,%s,'persona-compiler-0.2.0','Legacy player','{}','[]','{}')
                """,
                (str(blueprint.persona_id), str(record.version_id)),
            )
        migrate(upgrade_url, migrations)
        repository = PostgresPersonaRepository(upgrade_url, registry)
        assert repository.list_versions() == (record,)
        assert (
            PersonaVersioning.record(repository.list_versions()[0].blueprint).content_hash
            == record.content_hash
        )
        with psycopg2.connect(upgrade_url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT purpose,identity_summary FROM persona.compiled_profiles")
            assert cursor.fetchall() == [("SIMULATED_PLAYTESTER", "Legacy player")]
        # A new character profile can coexist after the immediately-prior-schema upgrade.
        character = PersonaVersioning.record(
            PersonaGenerator(registry).generate(2718, purpose=PersonaPurpose.CHARACTER)
        )
        repository.save_version(character)
        repository.save_compiled(
            PersonaCompiler().compile(
                character.blueprint, persona_version=str(character.version_id)
            )
        )
        assert len(repository.list_versions()) == 2
    finally:
        with maintenance.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
        maintenance.close()

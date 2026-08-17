from __future__ import annotations

import psycopg2
import pytest

from persona.compilation.compiler import PersonaCompiler
from persona.generation.generator import PersonaGenerator
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

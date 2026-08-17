from __future__ import annotations

import uuid
from pathlib import Path

import psycopg2
import pytest

from persona.generation.generator import PersonaGenerator
from persona.postgres import PostgresPersonaRepository
from persona.registry import PersonaSchemaRegistry
from persona.versioning import PersonaVersioning
from population.lifecycle import PopulationLifecycle
from population.postgres import PostgresPopulationRepository
from population.store import PopulationStore

pytestmark = pytest.mark.integration


def _seed_population_branch(integration_stack) -> tuple[uuid.UUID, uuid.UUID]:
    world_id, branch_id = uuid.uuid4(), uuid.uuid4()
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sim.worlds(id, slug, name) VALUES (%s, %s, 'Population Test')",
                (str(world_id), f"population-{uuid.uuid4().hex[:10]}"),
            )
            cursor.execute(
                """
                INSERT INTO sim.branches(id, world_id, branch_kind, name)
                VALUES (%s, %s, 'CANONICAL', 'canonical')
                """,
                (str(branch_id), str(world_id)),
            )
    return world_id, branch_id


def test_population_pool_and_activation_state_survive_repository_reload(
    integration_stack,
    tmp_path: Path,
) -> None:
    registry = PersonaSchemaRegistry.load_default()
    persona_repository = PostgresPersonaRepository(integration_stack.database_url, registry)
    persona_repository.sync_schema()

    population_id = uuid.uuid4()
    seed = 73
    path = tmp_path / "durable-population.parquet"
    PopulationStore(path).generate(size=4, seed=seed)
    world_id, branch_id = _seed_population_branch(integration_stack)
    repository = PostgresPopulationRepository(integration_stack.database_url)
    repository.save_pool(
        population_id=population_id,
        name=f"durable-{population_id.hex[:8]}",
        size=4,
        seed=seed,
        schema_version=registry.VERSION,
        path=path,
        world_id=world_id,
        branch_id=branch_id,
    )

    pools = repository.list_pools()
    pool = next(item for item in pools if item["population_id"] == str(population_id))
    assert Path(pool["artifact"]).resolve() == path.resolve()
    assert pool["materialized"] == 0
    assert pool["active"] == 0
    assert pool["world_id"] == str(world_id)
    assert pool["branch_id"] == str(branch_id)

    blueprint = PersonaGenerator(registry).generate(seed * 10_000_000)
    version = PersonaVersioning.record(blueprint)
    persona_repository.save_version(version)
    lifecycle = PopulationLifecycle(world_id, branch_id)
    member = lifecycle.materialize(
        blueprint.persona_id,
        profile=blueprint.dimensions,
        persistent_state={"finances": {"coins": 10}, "history": ["arrived"]},
        world_step=4,
    )
    repository.save_materialized(
        population_id=population_id,
        version=version,
        member=member,
        transition=lifecycle.history[-1],
    )
    assert (
        next(
            item for item in repository.list_pools() if item["population_id"] == str(population_id)
        )["materialized"]
        == 1
    )

    member = lifecycle.activate(
        blueprint.persona_id,
        active_state={
            "beliefs": ["market is unsafe"],
            "finances": {"coins": 8},
            "transient_path": [1, 2, 3],
        },
        world_step=5,
    )
    repository.save_transition(
        population_id=population_id,
        member=member,
        transition=lifecycle.history[-1],
        activation_state="ACTIVE",
    )
    assert (
        next(
            item for item in repository.list_pools() if item["population_id"] == str(population_id)
        )["active"]
        == 1
    )
    member = lifecycle.deactivate(
        blueprint.persona_id,
        compressed_state={"occupation": "merchant"},
        world_step=9,
    )
    repository.save_transition(
        population_id=population_id,
        member=member,
        transition=lifecycle.history[-1],
        activation_state="COMPRESSED",
    )
    restored = next(
        item for item in repository.list_pools() if item["population_id"] == str(population_id)
    )
    assert restored["materialized"] == 1
    assert restored["active"] == 0

    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT occupation, activation_state, persistent_state, active_state,
                   compressed_state, lifecycle_version, world_step
            FROM population.materialized_people
            WHERE world_id = %s AND branch_id = %s AND persona_id = %s
            """,
            (str(world_id), str(branch_id), str(blueprint.persona_id)),
        )
        (
            occupation,
            state,
            persistent_state,
            active_state,
            compressed_state,
            lifecycle_version,
            world_step,
        ) = cursor.fetchone()
    assert occupation == blueprint.dimensions["occupation_sector"]
    assert state == "COMPRESSED"
    assert persistent_state == {
        "beliefs": ["market is unsafe"],
        "finances": {"coins": 8},
        "history": ["arrived"],
        "occupation": "merchant",
    }
    assert active_state == {}
    assert compressed_state == {"occupation": "merchant"}
    assert lifecycle_version == 3
    assert world_step == 9

    restored_lifecycle = repository.load_lifecycle(population_id)
    restored_member = restored_lifecycle.get(blueprint.persona_id)
    assert restored_member == member
    assert restored_lifecycle.history == lifecycle.history

    reactivated = restored_lifecycle.activate(
        blueprint.persona_id,
        active_state={"attention_budget": 80},
        world_step=10,
    )
    repository.save_transition(
        population_id=population_id,
        member=reactivated,
        transition=restored_lifecycle.history[-1],
        activation_state="ACTIVE",
    )
    assert repository.load_lifecycle(population_id).get(blueprint.persona_id) == reactivated

    backward = restored_lifecycle.deactivate(
        blueprint.persona_id,
        compressed_state={},
        world_step=10,
    )
    with pytest.raises(ValueError, match="version or world step conflict"):
        repository.save_transition(
            population_id=population_id,
            member=backward.model_copy(update={"world_step": 8}),
            transition=restored_lifecycle.history[-1].model_copy(update={"world_step": 8}),
            activation_state="COMPRESSED",
        )

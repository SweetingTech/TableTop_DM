from __future__ import annotations

import uuid

import psycopg2
import psycopg2.extras
import pytest

from kernel.application import SimulationApplication
from kernel.postgres_control_plane import PostgresControlPlane
from kernel.state import stable_hash

pytestmark = pytest.mark.integration
EMPTY_HASH = "0" * 64


def _seed_world(connection, *, slug: str):
    ids = {name: uuid.uuid4() for name in ("world", "branch", "run", "actor_a", "actor_b")}
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO sim.worlds(id, slug, name) VALUES (%s, %s, %s)",
            (str(ids["world"]), slug, slug),
        )
        cursor.execute(
            """
            INSERT INTO sim.branches(id, world_id, branch_kind, name)
            VALUES (%s, %s, 'CANONICAL', 'canonical')
            """,
            (str(ids["branch"]), str(ids["world"])),
        )
        cursor.execute(
            """
            INSERT INTO sim.branch_projections(branch_id, world_id, state_hash)
            VALUES (%s, %s, %s)
            """,
            (str(ids["branch"]), str(ids["world"]), EMPTY_HASH),
        )
        cursor.execute(
            """
            INSERT INTO sim.runs(id, world_id, branch_id, run_kind, status)
            VALUES (%s, %s, %s, 'LIVE', 'RUNNING')
            """,
            (str(ids["run"]), str(ids["world"]), str(ids["branch"])),
        )
        cursor.execute(
            """
            INSERT INTO sim.actors(id, actor_kind, display_name)
            VALUES (%s, 'HUMAN', 'Actor A'), (%s, 'HUMAN', 'Actor B')
            """,
            (str(ids["actor_a"]), str(ids["actor_b"])),
        )
        cursor.execute(
            """
            INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
            VALUES (%s, %s, 'world.read'), (%s, %s, 'action.commit')
            """,
            (
                str(ids["world"]),
                str(ids["actor_a"]),
                str(ids["world"]),
                str(ids["actor_a"]),
            ),
        )
    connection.commit()
    return ids


def test_composite_foreign_keys_reject_cross_world_runs(integration_stack) -> None:
    with psycopg2.connect(integration_stack.admin_url) as connection:
        first = _seed_world(connection, slug="first-world")
        second = _seed_world(connection, slug="second-world")
        with (
            connection.cursor() as cursor,
            pytest.raises(psycopg2.errors.ForeignKeyViolation),
        ):
            cursor.execute(
                """
                INSERT INTO sim.runs(world_id, branch_id, run_kind, status)
                VALUES (%s, %s, 'LIVE', 'RUNNING')
                """,
                (str(first["world"]), str(second["branch"])),
            )
        connection.rollback()


def test_trial_branch_can_clone_logical_entity_ids(integration_stack) -> None:
    with psycopg2.connect(integration_stack.admin_url) as connection:
        ids = _seed_world(connection, slug="branch-identity-world")
        trial_branch = uuid.uuid4()
        entity_id = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sim.branches(id, world_id, branch_kind, name, seed)
                VALUES (%s, %s, 'TRIAL', 'trial-1', 17)
                """,
                (str(trial_branch), str(ids["world"])),
            )
            cursor.execute(
                """
                INSERT INTO sim.entities(id, world_id, branch_id, entity_type, name)
                VALUES (%s, %s, %s, 'TEST', 'Canonical entity'),
                       (%s, %s, %s, 'TEST', 'Trial clone')
                """,
                (
                    str(entity_id),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(entity_id),
                    str(ids["world"]),
                    str(trial_branch),
                ),
            )
            cursor.execute("SELECT count(*) FROM sim.entities WHERE id = %s", (str(entity_id),))
            assert cursor.fetchone()[0] == 2


def test_persona_identity_supports_version_lineage_with_one_schema(
    integration_stack,
) -> None:
    persona_id, first_version, second_version = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            INSERT INTO persona.schema_versions(version, schema_hash, definition, status)
            VALUES ('2.0.0-invariants', %s, '{}'::jsonb, 'ACTIVE')
            """,
            ("a" * 64,),
        )
        cursor.execute(
            """
            INSERT INTO persona.blueprints(
              persona_id, version_id, parent_version_id, schema_version, seed,
              generator_version, source, content_hash, dimensions, validation
            ) VALUES
              (%s, %s, NULL, '2.0.0-invariants', 17, 'test-1', 'synthetic', %s,
               '{"risk":"LOW"}'::jsonb, '{"status":"valid"}'::jsonb),
              (%s, %s, %s, '2.0.0-invariants', 17, 'test-1', 'manual', %s,
               '{"risk":"HIGH"}'::jsonb, '{"status":"valid"}'::jsonb)
            """,
            (
                str(persona_id),
                str(first_version),
                "b" * 64,
                str(persona_id),
                str(second_version),
                str(first_version),
                "c" * 64,
            ),
        )
        cursor.execute(
            """
            SELECT version_id, parent_version_id
            FROM persona.blueprints
            WHERE persona_id = %s
            ORDER BY created_at, version_id
            """,
            (str(persona_id),),
        )
        rows = [
            (str(version), str(parent) if parent else None) for version, parent in cursor.fetchall()
        ]
        assert len(rows) == 2
        assert (str(first_version), None) in rows
        assert (str(second_version), str(first_version)) in rows


def test_forced_rls_is_fail_closed_and_actor_scoped(integration_stack) -> None:
    event_a, event_b = uuid.uuid4(), uuid.uuid4()
    with psycopg2.connect(integration_stack.admin_url) as admin:
        ids = _seed_world(admin, slug="rls-world")
        with admin.cursor() as cursor:
            for event_id, visible_actor in (
                (event_a, ids["actor_a"]),
                (event_b, ids["actor_b"]),
            ):
                cursor.execute(
                    """
                    INSERT INTO sim.events(
                      event_id, event_version, contract_version, world_id, branch_id,
                      run_id, actor_id, event_type, payload, visible_to,
                      correlation_id, idempotency_key
                    ) VALUES (%s, 2, '2.0.0', %s, %s, %s, %s, 'test.visible',
                              '{}'::jsonb, %s::uuid[], %s, %s)
                    """,
                    (
                        str(event_id),
                        str(ids["world"]),
                        str(ids["branch"]),
                        str(ids["run"]),
                        str(ids["actor_a"]),
                        [str(visible_actor)],
                        str(uuid.uuid4()),
                        f"event-{event_id}",
                    ),
                )
        admin.commit()

    with (
        psycopg2.connect(integration_stack.database_url) as runtime,
        runtime.cursor() as cursor,
    ):
        cursor.execute("SELECT count(*) FROM sim.events")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["actor_a"]),))
        cursor.execute("SELECT event_id FROM sim.events ORDER BY event_id")
        assert [str(row[0]) for row in cursor.fetchall()] == [str(event_a)]

    with (
        psycopg2.connect(integration_stack.database_url) as runtime,
        runtime.cursor() as cursor,
    ):
        cursor.execute("SELECT set_config('app.actor_id', 'not-a-uuid', false)")
        cursor.execute("SELECT count(*) FROM sim.events")
        assert cursor.fetchone()[0] == 0


def test_secret_bearing_entity_rows_require_control_or_explicit_secret_read(
    integration_stack,
) -> None:
    controlled_entity, foreign_entity = uuid.uuid4(), uuid.uuid4()
    with psycopg2.connect(integration_stack.admin_url) as admin:
        ids = _seed_world(admin, slug="entity-read-scope")
        with admin.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sim.entities(
                  id, world_id, branch_id, entity_type, name,
                  controller_actor_id, secret_state
                ) VALUES
                  (%s,%s,%s,'TEST','Controlled',%s,'{"secret":"own"}'::jsonb),
                  (%s,%s,%s,'TEST','Foreign',%s,'{"secret":"hidden"}'::jsonb)
                """,
                (
                    str(controlled_entity),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(ids["actor_a"]),
                    str(foreign_entity),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(ids["actor_b"]),
                ),
            )
        admin.commit()

    with psycopg2.connect(integration_stack.database_url) as runtime:
        with runtime.cursor() as cursor:
            cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["actor_a"]),))
            cursor.execute("SELECT id, secret_state FROM sim.entities ORDER BY id")
            rows = cursor.fetchall()
            assert [(str(row[0]), row[1]) for row in rows] == [
                (str(controlled_entity), {"secret": "own"})
            ]

    with psycopg2.connect(integration_stack.admin_url) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                """INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s,%s,'entity.read.secret')""",
                (str(ids["world"]), str(ids["actor_a"])),
            )
        admin.commit()

    with psycopg2.connect(integration_stack.database_url) as runtime:
        with runtime.cursor() as cursor:
            cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["actor_a"]),))
            cursor.execute("SELECT id FROM sim.entities ORDER BY id")
            assert {str(row[0]) for row in cursor.fetchall()} == {
                str(controlled_entity),
                str(foreign_entity),
            }


def test_ledger_is_append_only_even_for_owner(integration_stack) -> None:
    with psycopg2.connect(integration_stack.admin_url) as connection:
        ids = _seed_world(connection, slug="append-only-world")
        event_id = uuid.uuid4()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sim.events(
                  event_id, event_version, contract_version, world_id, branch_id,
                  run_id, actor_id, event_type, payload, visible_to, correlation_id
                ) VALUES (%s, 2, '2.0.0', %s, %s, %s, %s, 'test.append',
                          '{}'::jsonb, %s::uuid[], %s)
                """,
                (
                    str(event_id),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(ids["run"]),
                    str(ids["actor_a"]),
                    [str(ids["actor_a"])],
                    str(uuid.uuid4()),
                ),
            )
        connection.commit()
        with (
            connection.cursor() as cursor,
            pytest.raises(psycopg2.errors.ObjectNotInPrerequisiteState, match="append-only"),
        ):
            cursor.execute(
                "UPDATE sim.events SET payload = '{\"changed\":true}' WHERE event_id = %s",
                (str(event_id),),
            )
        connection.rollback()


def test_control_plane_sync_never_overwrites_command_owned_state(
    integration_stack, tmp_path
) -> None:
    simulation = SimulationApplication(tmp_path / "snapshots")
    ids = simulation.bootstrap_demo()
    control = PostgresControlPlane(integration_stack.database_url)
    control.sync(simulation)
    durable_state = {"durable": {"singleton": {"value": 17}}}
    durable_hash = stable_hash(durable_state)
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE sim.branch_projections
                SET version=7, state=%s::jsonb, state_hash=%s
                WHERE world_id=%s AND branch_id=%s
                """,
                (
                    psycopg2.extras.Json(durable_state),
                    durable_hash,
                    str(ids["world_id"]),
                    str(ids["branch_id"]),
                ),
            )
            cursor.execute(
                """
                UPDATE sim.entities SET secret_state='{"durable":true}'::jsonb
                WHERE world_id=%s AND branch_id=%s AND id=%s
                """,
                (str(ids["world_id"]), str(ids["branch_id"]), str(ids["hero_id"])),
            )

    control.sync(simulation)
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version, state, state_hash
                FROM sim.branch_projections
                WHERE world_id=%s AND branch_id=%s
                """,
                (str(ids["world_id"]), str(ids["branch_id"])),
            )
            assert cursor.fetchone() == (7, durable_state, durable_hash)
            cursor.execute(
                """
                SELECT secret_state FROM sim.entities
                WHERE world_id=%s AND branch_id=%s AND id=%s
                """,
                (str(ids["world_id"]), str(ids["branch_id"]), str(ids["hero_id"])),
            )
            assert cursor.fetchone()[0] == {"durable": True}

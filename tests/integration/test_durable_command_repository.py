from __future__ import annotations

import uuid

import psycopg2
import pytest

from domains.tabletop.entities import command_definition as spawn_definition
from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    Actor,
    ActorKind,
    BranchKind,
    CommandProposal,
    CommandResult,
    StateDelta,
)
from kernel.postgres_repository import PostgresCommandRepository
from kernel.state import stable_hash

pytestmark = pytest.mark.integration


def _handler(proposal: CommandProposal, _state) -> CommandResult:
    return CommandResult(
        result={"accepted_action": proposal.parameters["action"]},
        deltas=(
            StateDelta(
                projection="test",
                operation="INCREMENT",
                values={"count": 1},
            ),
        ),
        domain_tags=("test.integration",),
    )


def _seed_durable_command(integration_stack):
    ids = {
        name: uuid.uuid4() for name in ("world", "branch", "run", "actor", "observer", "outsider")
    }
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sim.worlds(id, slug, name) VALUES (%s, %s, 'Durable Test')",
                (str(ids["world"]), f"durable-{uuid.uuid4().hex[:10]}"),
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
                (str(ids["branch"]), str(ids["world"]), stable_hash({})),
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
                VALUES (%s, 'AGENT', 'Durable actor'),
                       (%s, 'HUMAN', 'World observer'),
                       (%s, 'HUMAN', 'Unprivileged outsider')
                """,
                (str(ids["actor"]), str(ids["observer"]), str(ids["outsider"])),
            )
            cursor.execute(
                """
                INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s, %s, 'action.commit'), (%s, %s, 'test.write'),
                       (%s, %s, 'world.read.all'),
                       (%s, %s, 'entity.create'), (%s, %s, 'entity.control')
                """,
                (
                    str(ids["world"]),
                    str(ids["actor"]),
                    str(ids["world"]),
                    str(ids["actor"]),
                    str(ids["world"]),
                    str(ids["observer"]),
                    str(ids["world"]),
                    str(ids["actor"]),
                    str(ids["world"]),
                    str(ids["actor"]),
                ),
            )
    actor = Actor(
        actor_id=ids["actor"],
        kind=ActorKind.AGENT,
        display_name="Durable actor",
        capabilities=frozenset({"action.commit", "test.write", "entity.create", "entity.control"}),
    )
    definition = CommandDefinition(
        command_type="test.increment",
        required_capabilities=frozenset({"test.write"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        handler=_handler,
    )
    return ids, actor, definition


def _proposal(ids, *, key: str) -> CommandProposal:
    return CommandProposal(
        command_type="test.increment",
        world_id=ids["world"],
        branch_id=ids["branch"],
        run_id=ids["run"],
        actor_id=ids["actor"],
        parameters={"action": "increment"},
        idempotency_key=key,
        seed=17,
    )


def _spawn_proposal(ids, *, key: str, entity_id: uuid.UUID) -> CommandProposal:
    return CommandProposal(
        command_type="tabletop.entity.spawn",
        world_id=ids["world"],
        branch_id=ids["branch"],
        run_id=ids["run"],
        actor_id=ids["actor"],
        parameters={
            "entity_id": str(entity_id),
            "name": "Secret witness",
            "entity_type": "NPC",
            "public_state": {"x": 4, "y": 7},
            "secret_state": {"true_name": "Never Ledgered"},
            "controller_actor_id": str(ids["actor"]),
        },
        idempotency_key=key,
    )


def test_durable_command_is_idempotent_and_writes_outbox(integration_stack) -> None:
    ids, actor, definition = _seed_durable_command(integration_stack)
    repository = PostgresCommandRepository(integration_stack.database_url)
    proposal = _proposal(ids, key="same-command")

    first = repository.execute(proposal, actor, definition)
    second = repository.execute(proposal, actor, definition)

    assert second == first
    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT version, state, state_hash FROM sim.branch_projections WHERE branch_id = %s",
            (str(ids["branch"]),),
        )
        version, state, state_hash = cursor.fetchone()
        assert version == 1
        assert state == {"test": {"singleton": {"count": 1}}}
        assert state_hash == first.state_hash
        cursor.execute("SELECT count(*) FROM sim.command_log WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM sim.events WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone()[0] == 1
        cursor.execute(
            "SELECT cardinality(observed_by) FROM sim.events WHERE run_id = %s",
            (str(ids["run"]),),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT count(*) FROM sim.outbox outbox
            JOIN sim.events event ON event.event_id = outbox.event_id
            WHERE event.run_id = %s
            """,
            (str(ids["run"]),),
        )
        assert cursor.fetchone()[0] == 1

    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["observer"]),))
        cursor.execute("SELECT event_id FROM sim.events WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone() == (str(first.event.event_id),)

    with (
        psycopg2.connect(integration_stack.database_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["outsider"]),))
        cursor.execute("SELECT count(*) FROM sim.events WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone()[0] == 0


def test_durable_command_rolls_back_projection_log_event_and_outbox(
    integration_stack, monkeypatch
) -> None:
    ids, actor, definition = _seed_durable_command(integration_stack)
    repository = PostgresCommandRepository(integration_stack.database_url)

    def fail_event_insert(_cursor, _event) -> None:
        raise RuntimeError("forced event persistence failure")

    monkeypatch.setattr(repository, "_insert_event", fail_event_insert)
    with pytest.raises(RuntimeError, match="forced event persistence failure"):
        repository.execute(_proposal(ids, key="must-roll-back"), actor, definition)

    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT version, state FROM sim.branch_projections WHERE branch_id = %s",
            (str(ids["branch"]),),
        )
        assert cursor.fetchone() == (0, {})
        cursor.execute("SELECT count(*) FROM sim.command_log WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT count(*) FROM sim.events WHERE run_id = %s", (str(ids["run"]),))
        assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT count(*) FROM sim.outbox outbox
            JOIN sim.events event ON event.event_id = outbox.event_id
            WHERE event.run_id = %s
            """,
            (str(ids["run"]),),
        )
        assert cursor.fetchone()[0] == 0


def test_entity_spawn_is_atomic_and_redacts_secret_ledger_fields(
    integration_stack, monkeypatch
) -> None:
    ids, actor, _definition = _seed_durable_command(integration_stack)
    repository = PostgresCommandRepository(integration_stack.database_url)
    entity_id = uuid.uuid4()
    receipt = repository.execute(
        _spawn_proposal(ids, key="secret-spawn", entity_id=entity_id),
        actor,
        spawn_definition(),
    )
    assert "Never Ledgered" not in receipt.result.model_dump_json()

    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            """
            SELECT secret_state, controller_actor_id
            FROM sim.entities
            WHERE world_id=%s AND branch_id=%s AND id=%s
            """,
            (str(ids["world"]), str(ids["branch"]), str(entity_id)),
        )
        secret_state, controller_actor_id = cursor.fetchone()
        assert secret_state == {"true_name": "Never Ledgered"}
        assert controller_actor_id == str(ids["actor"])
        cursor.execute(
            """
            SELECT parameters, result
            FROM sim.command_log
            WHERE run_id=%s AND idempotency_key='secret-spawn'
            """,
            (str(ids["run"]),),
        )
        parameters, result = cursor.fetchone()
        assert parameters["secret_state"] == "[REDACTED]"
        assert "Never Ledgered" not in str(parameters)
        assert "Never Ledgered" not in str(result)
        assert "entity_mutations" not in result
        cursor.execute(
            """
            SELECT event.payload, outbox.payload
            FROM sim.events event
            JOIN sim.outbox outbox ON outbox.event_id=event.event_id
            WHERE event.run_id=%s AND event.idempotency_key='secret-spawn'
            """,
            (str(ids["run"]),),
        )
        event_payload, outbox_payload = cursor.fetchone()
        assert "Never Ledgered" not in str(event_payload)
        assert "Never Ledgered" not in str(outbox_payload)

    failed_ids, failed_actor, _definition = _seed_durable_command(integration_stack)
    failed_repository = PostgresCommandRepository(integration_stack.database_url)
    failed_entity_id = uuid.uuid4()

    def fail_event_insert(_cursor, _event) -> None:
        raise RuntimeError("forced entity event persistence failure")

    monkeypatch.setattr(failed_repository, "_insert_event", fail_event_insert)
    with pytest.raises(RuntimeError, match="forced entity event persistence failure"):
        failed_repository.execute(
            _spawn_proposal(
                failed_ids,
                key="failed-secret-spawn",
                entity_id=failed_entity_id,
            ),
            failed_actor,
            spawn_definition(),
        )

    with (
        psycopg2.connect(integration_stack.admin_url) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "SELECT version, state FROM sim.branch_projections WHERE branch_id=%s",
            (str(failed_ids["branch"]),),
        )
        assert cursor.fetchone() == (0, {})
        cursor.execute(
            "SELECT count(*) FROM sim.entities WHERE branch_id=%s AND id=%s",
            (str(failed_ids["branch"]), str(failed_entity_id)),
        )
        assert cursor.fetchone()[0] == 0
        for table in ("command_log", "events"):
            cursor.execute(
                f"SELECT count(*) FROM sim.{table} WHERE run_id=%s",
                (str(failed_ids["run"]),),
            )
            assert cursor.fetchone()[0] == 0
        cursor.execute(
            """
            SELECT count(*) FROM sim.outbox outbox
            JOIN sim.events event ON event.event_id = outbox.event_id
            WHERE event.run_id = %s
            """,
            (str(failed_ids["run"]),),
        )
        assert cursor.fetchone()[0] == 0

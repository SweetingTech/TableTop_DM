from __future__ import annotations

import json
import uuid

import psycopg2
import pytest

from cognition.projector import WorldEventProjector
from domains.tabletop.dialogue import command_definitions as dialogue_definitions
from domains.tabletop.entities import command_definition as spawn_definition
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandBus, CommandDefinition
from kernel.contracts import (
    Actor,
    ActorKind,
    BranchKind,
    CommandProposal,
    CommandResult,
    StateDelta,
)
from kernel.event_factory import EventFactory
from kernel.postgres_repository import PostgresCommandRepository
from kernel.state import BranchState, InMemoryStateStore, stable_hash

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


def test_spatial_perceptions_are_atomic_rls_scoped_idempotent_and_match_reference(
    integration_stack,
    monkeypatch,
) -> None:
    ids, actor, _definition = _seed_durable_command(integration_stack)
    speaker, listener, hidden = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    projection = {
        "tabletop.entities": {
            str(speaker): {"name": "Speaker", "x": 1, "y": 1, "zone_id": "common"},
            str(listener): {"name": "Listener", "x": 2, "y": 1, "zone_id": "common"},
            str(hidden): {"name": "Hidden", "x": 1, "y": 1, "zone_id": "back"},
        },
        "tabletop.spatial.zones": {
            "common": {"name": "Common room"},
            "back": {"name": "Back room"},
        },
        "tabletop.spatial.portals": {
            str(uuid.uuid4()): {
                "from_zone_id": "common",
                "to_zone_id": "back",
                "kind": "DOOR",
                "state": "CLOSED",
                "sight_transmission": 0,
                "sound_transmission": 1,
                "movement_allowed": False,
            }
        },
        "tabletop.sensory_profiles": {
            str(speaker): {"controller_actor_id": str(ids["actor"])},
            str(listener): {"controller_actor_id": str(ids["outsider"])},
        },
    }
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE sim.branch_projections
                SET state=%s::jsonb, state_hash=%s
                WHERE branch_id=%s""",
                (json.dumps(projection), stable_hash(projection), str(ids["branch"])),
            )
            cursor.execute(
                """INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s,%s,'action.propose'),(%s,%s,'entity.act')""",
                (
                    str(ids["world"]),
                    str(ids["actor"]),
                    str(ids["world"]),
                    str(ids["actor"]),
                ),
            )
            for entity_id, name, controller in (
                (speaker, "Speaker", ids["actor"]),
                (listener, "Listener", ids["outsider"]),
                (hidden, "Hidden", ids["outsider"]),
            ):
                cursor.execute(
                    """INSERT INTO sim.entities(
                      id,world_id,branch_id,entity_type,name,public_state,controller_actor_id
                    ) VALUES (%s,%s,%s,'NPC',%s,'{}',%s)""",
                    (
                        str(entity_id),
                        str(ids["world"]),
                        str(ids["branch"]),
                        name,
                        str(controller),
                    ),
                )
    actor = actor.model_copy(
        update={
            "capabilities": actor.capabilities | {"action.propose", "entity.act"},
            "controlled_entity_ids": frozenset({speaker}),
        }
    )
    proposal = CommandProposal(
        command_type="tabletop.dialogue.speak",
        world_id=ids["world"],
        branch_id=ids["branch"],
        run_id=ids["run"],
        actor_id=ids["actor"],
        embodied_entity_id=speaker,
        parameters={"text": "The king is dead.", "volume": "NORMAL"},
        idempotency_key="durable-spatial-speech",
    )
    definition = next(
        item for item in dialogue_definitions() if item.command_type == "tabletop.dialogue.speak"
    )
    factory = EventFactory(GridSpatialPerceptionResolver())
    repository = PostgresCommandRepository(integration_stack.database_url, factory)
    durable = repository.execute(proposal, actor, definition)
    duplicate = repository.execute(proposal, actor, definition)
    assert [item.model_dump(mode="json") for item in duplicate.perceptions] == [
        item.model_dump(mode="json") for item in durable.perceptions
    ]
    assert {item.observer_entity_id for item in durable.perceptions} == {speaker, listener}

    reference_store = InMemoryStateStore()
    reference_store.add(BranchState(ids["world"], ids["branch"], BranchKind.CANONICAL, projection))
    reference_bus = CommandBus(reference_store, factory)
    reference_bus.register(definition)
    reference = reference_bus.execute(proposal, actor)
    assert reference.perceptions == durable.perceptions
    assert reference.event.model_dump(exclude={"created_at"}) == durable.event.model_dump(
        exclude={"created_at"}
    )

    with psycopg2.connect(integration_stack.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.actor_id', %s, false)", (str(ids["outsider"]),))
            cursor.execute(
                "SELECT count(*) FROM sim.events WHERE event_id=%s",
                (str(durable.event.event_id),),
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                "SELECT observer_entity_id FROM sim.event_perceptions WHERE event_id=%s",
                (str(durable.event.event_id),),
            )
            assert cursor.fetchall() == [(str(listener),)]

    assert WorldEventProjector(integration_stack.database_url).run_once() >= 1
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT published_at IS NOT NULL FROM sim.outbox WHERE event_id=%s",
                (str(durable.event.event_id),),
            )
            assert cursor.fetchone() == (True,)
            cursor.execute(
                "SELECT observer_entity_id FROM cognition.observations WHERE source_event_id=%s",
                (str(durable.event.event_id),),
            )
            assert {row[0] for row in cursor.fetchall()} == {str(speaker), str(listener)}

    failed_proposal = proposal.model_copy(
        update={
            "command_id": uuid.uuid4(),
            "correlation_id": uuid.uuid4(),
            "idempotency_key": "durable-spatial-perception-write-failure",
        }
    )
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT version FROM sim.branch_projections WHERE branch_id=%s",
                (str(ids["branch"]),),
            )
            version_before = cursor.fetchone()[0]

    def reject_perceptions(_cursor, _perceptions) -> None:
        raise psycopg2.IntegrityError("forced perception persistence failure")

    monkeypatch.setattr(repository, "_insert_perceptions", reject_perceptions)
    with pytest.raises(psycopg2.IntegrityError, match="forced perception"):
        repository.execute(failed_proposal, actor, definition)

    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT version FROM sim.branch_projections WHERE branch_id=%s",
                (str(ids["branch"]),),
            )
            assert cursor.fetchone()[0] == version_before
            cursor.execute(
                """SELECT
                     (SELECT count(*) FROM sim.command_log WHERE idempotency_key=%s),
                     (SELECT count(*) FROM sim.events WHERE idempotency_key=%s),
                     (SELECT count(*) FROM sim.outbox o JOIN sim.events e USING(event_id)
                       WHERE e.idempotency_key=%s)""",
                (failed_proposal.idempotency_key,) * 3,
            )
            assert cursor.fetchone() == (0, 0, 0)

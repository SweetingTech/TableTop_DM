from __future__ import annotations

import uuid

import psycopg2
import pytest

from cognition.engine import (
    DecisionAction,
    DecisionRequest,
    LayeredDecisionEngine,
    SubjectiveStatePipeline,
)
from cognition.models import MindState, RelationshipVector, RuntimeAssignment
from cognition.perception import PerceptionProfile
from cognition.postgres import PostgresMindRepository
from cognition.relationships import RelationshipChangeRecord, RelationshipEngine
from cognition.store import MindStore
from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    Actor,
    ActorKind,
    BranchKind,
    CommandProposal,
    CommandResult,
    StateDelta,
)
from kernel.perception_contracts import PerceptionGrant
from kernel.postgres_repository import PostgresCommandRepository
from kernel.state import stable_hash
from persona.compilation.compiler import PersonaCompiler
from persona.generation.generator import PersonaGenerator
from persona.postgres import PostgresPersonaRepository
from persona.registry import PersonaSchemaRegistry
from persona.versioning import PersonaVersioning

pytestmark = pytest.mark.integration


class _CognitionPersonaRegistry(PersonaSchemaRegistry):
    VERSION = "2.0.0-cognition-integration"


def _handler(proposal: CommandProposal, _state) -> CommandResult:
    return CommandResult(
        result={"accepted_action": proposal.parameters["action"]},
        deltas=(StateDelta(projection="test", operation="INCREMENT", values={"count": 1}),),
        domain_tags=("test.cognition",),
    )


def _seed_cognition_world(integration_stack):
    ids = {
        name: uuid.uuid4()
        for name in ("world", "branch", "run", "actor", "other_actor", "hero", "target")
    }
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sim.worlds(id, slug, name) VALUES (%s, %s, 'Cognition Test')",
                (str(ids["world"]), f"cognition-{uuid.uuid4().hex[:10]}"),
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
                VALUES (%s, 'AGENT', 'Cognitive hero'),
                       (%s, 'AGENT', 'Unauthorized observer')
                """,
                (str(ids["actor"]), str(ids["other_actor"])),
            )
            cursor.execute(
                """
                INSERT INTO sim.entities(
                  id, world_id, branch_id, entity_type, name, controller_actor_id
                ) VALUES (%s, %s, %s, 'HERO', 'Hero', %s),
                         (%s, %s, %s, 'NPC', 'Target', NULL)
                """,
                (
                    str(ids["hero"]),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(ids["actor"]),
                    str(ids["target"]),
                    str(ids["world"]),
                    str(ids["branch"]),
                ),
            )
            cursor.executemany(
                """
                INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s, %s, %s)
                """,
                [
                    (str(ids["world"]), str(ids["actor"]), capability)
                    for capability in (
                        "action.commit",
                        "entity.control",
                        "mind.read.all",
                        "mind.write.all",
                        "test.write",
                    )
                ],
            )
    return ids


def test_decision_commit_observation_and_mind_reload_are_actor_scoped(
    integration_stack,
) -> None:
    ids = _seed_cognition_world(integration_stack)
    registry = _CognitionPersonaRegistry.load_default()
    personas = PostgresPersonaRepository(integration_stack.database_url, registry)
    personas.sync_schema()
    blueprint = PersonaGenerator(registry).generate(90210, {"risk_tolerance": "LOW"})
    version = PersonaVersioning.record(blueprint)
    personas.save_version(version)
    compiled = PersonaCompiler().compile(blueprint, persona_version=str(version.version_id))
    personas.save_compiled(compiled)

    outcome = LayeredDecisionEngine().decide(
        DecisionRequest(
            persona=compiled,
            world_id=ids["world"],
            branch_id=ids["branch"],
            run_id=ids["run"],
            actor_id=ids["actor"],
            embodied_entity_id=ids["hero"],
            seed=17,
            idempotency_key="cognition-decision-1",
            situation={"blocked": False},
            actions=(
                DecisionAction(
                    action="ADVANCE",
                    command_type="test.increment",
                    parameters={"action": "advance"},
                    utility_factors={"goal_alignment": 1.0},
                ),
            ),
        )
    )
    mind_repository = PostgresMindRepository(integration_stack.database_url)
    mind_repository.save_decision(outcome)

    actor = Actor(
        actor_id=ids["actor"],
        kind=ActorKind.AGENT,
        display_name="Cognitive hero",
        capabilities=frozenset(
            {"action.commit", "entity.control", "mind.read.all", "mind.write.all", "test.write"}
        ),
        controlled_entity_ids=frozenset({ids["hero"]}),
    )
    receipt = PostgresCommandRepository(integration_stack.database_url).execute(
        outcome.proposal,
        actor,
        CommandDefinition(
            command_type="test.increment",
            required_capabilities=frozenset({"entity.control", "test.write"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
            handler=_handler,
        ),
    )
    update = SubjectiveStatePipeline().process(
        receipt.event,
        PerceptionProfile(
            observer_entity_id=ids["hero"],
            observer_actor_id=ids["actor"],
        ),
        grant=PerceptionGrant(
            event_id=receipt.event.event_id,
            world_id=ids["world"],
            branch_id=ids["branch"],
            observer_entity_id=ids["hero"],
            controller_actor_id=ids["actor"],
            modalities=("SIGHT",),
            outcome="DIRECT",
            confidence=1,
            resolver_version="integration-fixture-1",
            spatial_context_hash="0" * 64,
        ),
        memory_summary="I advanced after weighing the available actions.",
        importance=0.8,
    )
    minds = MindStore()
    minds.initialize(MindState(entity_id=ids["hero"], goals=("advance",)))
    state = minds.apply_subjective_update(ids["hero"], update)
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """DELETE FROM sim.actor_capabilities
                WHERE world_id=%s AND actor_id=%s
                  AND capability IN ('mind.read.all', 'mind.write.all')""",
                (str(ids["world"]), str(ids["actor"])),
            )
            assert cursor.rowcount == 2
    mind_repository.save_subjective_update(
        world_id=ids["world"],
        branch_id=ids["branch"],
        actor_id=ids["actor"],
        state=state,
        update=update,
    )
    relationship_change = RelationshipChangeRecord.from_change(
        RelationshipEngine().apply(RelationshipVector(), "kept_promise"),
        world_id=ids["world"],
        branch_id=ids["branch"],
        source_entity_id=ids["hero"],
        target_entity_id=ids["target"],
        source_event_id=receipt.event.event_id,
        actor_id=ids["actor"],
        policy_version=RelationshipEngine.VERSION,
    )
    assert mind_repository.save_relationship_change(relationship_change) == relationship_change
    assert mind_repository.save_relationship_change(relationship_change) == relationship_change

    restored = mind_repository.inspect(
        world_id=ids["world"],
        branch_id=ids["branch"],
        entity_id=ids["hero"],
        actor_id=ids["actor"],
    )
    assert restored["mind_state"]["goals"] == ["advance"]
    assert len(restored["decisions"]) == 1
    assert len(restored["observations"]) == 1
    assert len(restored["memories"]) == 1
    assert restored["relationships"][0]["trust"] == 12
    assert restored["relationship_changes"][0]["source_event_id"] == str(receipt.event.event_id)
    assert restored["relationship_changes"][0]["applied_deltas"]["trust"] == 12

    unauthorized = mind_repository.inspect(
        world_id=ids["world"],
        branch_id=ids["branch"],
        entity_id=ids["hero"],
        actor_id=ids["other_actor"],
    )
    assert unauthorized == {
        "mind_state": None,
        "observations": [],
        "beliefs": [],
        "memories": [],
        "relationships": [],
        "relationship_changes": [],
        "decisions": [],
        "belief_evidence": [],
    }

    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.Error, match="append-only"):
                cursor.execute(
                    "UPDATE cognition.relationship_changes SET event_type='forged' WHERE id=%s",
                    (str(relationship_change.change_id),),
                )


def test_mind_write_authority_can_apply_visible_causal_relationship_change(
    integration_stack,
) -> None:
    ids = _seed_cognition_world(integration_stack)
    mind_writer_id = uuid.uuid4()
    source_event_id = uuid.uuid4()
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO sim.actors(id, actor_kind, display_name)
                VALUES (%s, 'SYSTEM', 'Relationship mind writer')""",
                (str(mind_writer_id),),
            )
            cursor.execute(
                """INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s, %s, 'mind.write.all')""",
                (str(ids["world"]), str(mind_writer_id)),
            )
            cursor.execute(
                """
                INSERT INTO sim.events(
                  event_id, event_version, contract_version, world_id, branch_id,
                  run_id, actor_id, event_type, payload, visible_to, correlation_id
                ) VALUES (%s, 2, '2.0.0', %s, %s, %s, %s,
                          'test.relationship_source', '{}'::jsonb, %s::uuid[], %s)
                """,
                (
                    str(source_event_id),
                    str(ids["world"]),
                    str(ids["branch"]),
                    str(ids["run"]),
                    str(mind_writer_id),
                    [str(mind_writer_id)],
                    str(uuid.uuid4()),
                ),
            )

    record = RelationshipChangeRecord.from_change(
        RelationshipEngine().apply(RelationshipVector(), "saved_life"),
        world_id=ids["world"],
        branch_id=ids["branch"],
        source_entity_id=ids["hero"],
        target_entity_id=ids["target"],
        source_event_id=source_event_id,
        actor_id=mind_writer_id,
        policy_version=RelationshipEngine.VERSION,
    )
    repository = PostgresMindRepository(integration_stack.database_url)

    assert repository.save_relationship_change(record) == record
    assert (
        repository.inspect(
            world_id=ids["world"],
            branch_id=ids["branch"],
            entity_id=ids["hero"],
            actor_id=mind_writer_id,
        )["relationships"][0]["trust"]
        == 20
    )


def test_runtime_assignments_persist_with_controller_or_mind_write_authority(
    integration_stack,
) -> None:
    ids = _seed_cognition_world(integration_stack)
    repository = PostgresMindRepository(integration_stack.database_url)
    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """DELETE FROM sim.actor_capabilities
                WHERE world_id=%s AND actor_id=%s
                  AND capability IN ('mind.read.all', 'mind.write.all')""",
                (str(ids["world"]), str(ids["actor"])),
            )

    controlled = RuntimeAssignment(
        world_id=ids["world"],
        branch_id=ids["branch"],
        run_id=ids["run"],
        entity_id=ids["hero"],
        runtime_kind="UTILITY",
        runtime_config={"source": "controller"},
    )
    assert repository.save_runtime_assignment(controlled, actor_id=ids["actor"]) == controlled
    assert (
        repository.load_runtime_assignment(
            world_id=ids["world"],
            branch_id=ids["branch"],
            run_id=ids["run"],
            entity_id=ids["hero"],
            actor_id=ids["actor"],
        )
        == controlled
    )
    assert repository.list_runtime_assignments(
        world_id=ids["world"],
        branch_id=ids["branch"],
        entity_id=ids["hero"],
        actor_id=ids["actor"],
    ) == (controlled,)
    assert (
        repository.load_runtime_assignment(
            world_id=ids["world"],
            branch_id=ids["branch"],
            run_id=ids["run"],
            entity_id=ids["hero"],
            actor_id=ids["other_actor"],
        )
        is None
    )
    with pytest.raises(psycopg2.Error):
        repository.save_runtime_assignment(controlled, actor_id=ids["other_actor"])

    with psycopg2.connect(integration_stack.admin_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO sim.actor_capabilities(world_id, actor_id, capability)
                VALUES (%s, %s, 'mind.write.all')""",
                (str(ids["world"]), str(ids["other_actor"])),
            )
    global_assignment = RuntimeAssignment(
        world_id=ids["world"],
        branch_id=ids["branch"],
        run_id=ids["run"],
        entity_id=ids["target"],
        runtime_kind="PLANNER",
    )
    assert (
        repository.save_runtime_assignment(global_assignment, actor_id=ids["other_actor"])
        == global_assignment
    )
    with pytest.raises(psycopg2.Error):
        repository.save_runtime_assignment(
            global_assignment.model_copy(update={"branch_id": uuid.uuid4()}),
            actor_id=ids["other_actor"],
        )

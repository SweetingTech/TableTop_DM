import uuid
from datetime import UTC, datetime, timedelta

import pytest

from domains.tabletop.onboarding import command_definition
from kernel.branching import ConsequencePackage, promotion_definition
from kernel.command_bus import CommandBus, CommandDefinition
from kernel.contracts import (
    Actor,
    ActorKind,
    BranchKind,
    CommandProposal,
    CommandResult,
    StateDelta,
)
from kernel.errors import AuthorizationDenied
from kernel.replay import ReplayDivergence, ReplayEngine, ReplayRecord
from kernel.scheduling import DeterministicScheduler
from kernel.state import BranchState, InMemoryStateStore

pytestmark = pytest.mark.unit


def ids():
    return [uuid.uuid4() for _ in range(6)]


def test_duplicate_returns_original_receipt_without_second_mutation():
    world, branch, run, actor_id, entity_id, _ = ids()
    store = InMemoryStateStore()
    state = BranchState(world, branch, BranchKind.TRIAL)
    store.add(state)
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        display_name="fixture",
        capabilities=frozenset({"action.propose", "entity.act"}),
        controlled_entity_ids=frozenset({entity_id}),
    )
    bus = CommandBus(store)
    bus.register(command_definition())
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world,
        branch_id=branch,
        run_id=run,
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        parameters={"action": "INVALID_ACTION"},
        idempotency_key="same",
    )
    first = bus.execute(proposal, actor)
    second = bus.execute(proposal, actor)
    assert second == first
    assert state.version == 1
    assert state.projections["tabletop.onboarding"][str(entity_id)]["invalid_actions"] == 1


def test_handler_exception_cannot_leak_working_state_mutation():
    world, branch, run, actor_id, _, _ = ids()
    store = InMemoryStateStore()
    state = BranchState(world, branch, BranchKind.TRIAL, {"counter": {"singleton": {"n": 1}}})
    store.add(state)

    def corrupt_then_fail(_proposal, working):
        working.projections["counter"]["singleton"]["n"] = 999
        raise RuntimeError("no commit")

    bus = CommandBus(store)
    bus.register(
        CommandDefinition(
            command_type="test.atomic.fail",
            required_capabilities=frozenset({"action.propose"}),
            allowed_branch_kinds=frozenset({BranchKind.TRIAL}),
            handler=corrupt_then_fail,
        )
    )
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.SYSTEM,
        display_name="fixture",
        capabilities=frozenset({"action.propose"}),
    )
    proposal = CommandProposal(
        command_type="test.atomic.fail",
        world_id=world,
        branch_id=branch,
        run_id=run,
        actor_id=actor_id,
        idempotency_key="fail",
    )
    with pytest.raises(RuntimeError):
        bus.execute(proposal, actor)
    assert state.projections["counter"]["singleton"]["n"] == 1
    assert state.version == 0


def test_entity_control_is_checked_not_merely_capability_name():
    world, branch, run, actor_id, entity_id, _ = ids()
    store = InMemoryStateStore()
    store.add(BranchState(world, branch, BranchKind.TRIAL))
    bus = CommandBus(store)
    bus.register(command_definition())
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        display_name="intruder",
        capabilities=frozenset({"action.propose", "entity.act"}),
    )
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world,
        branch_id=branch,
        run_id=run,
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        parameters={"action": "START"},
        idempotency_key="intrusion",
    )
    with pytest.raises(AuthorizationDenied):
        bus.execute(proposal, actor)


def test_replay_detects_divergence_and_scheduler_is_stable():
    world, branch, run, actor_id, _, _ = ids()
    proposal = CommandProposal(
        command_type="test.counter.increment",
        world_id=world,
        branch_id=branch,
        run_id=run,
        actor_id=actor_id,
        idempotency_key="one",
    )
    base = BranchState(world, branch, BranchKind.TRIAL)
    result = CommandResult(
        deltas=(StateDelta(projection="counter", operation="INCREMENT", values={"n": 1}),)
    )
    expected = base.working_copy()
    expected.apply(result.deltas[0])
    record = ReplayRecord(proposal=proposal, result=result, expected_state_hash=expected.state_hash)
    assert ReplayEngine.replay(base, (record,)).state_hash == expected.state_hash
    with pytest.raises(ReplayDivergence):
        ReplayEngine.replay(base, (record.model_copy(update={"expected_state_hash": "0" * 64}),))
    scheduler = DeterministicScheduler()
    now = datetime.now(UTC)
    scheduler.schedule(now + timedelta(seconds=1), proposal)
    later = proposal.model_copy(update={"idempotency_key": "two"})
    scheduler.schedule(now + timedelta(seconds=1), later)
    assert scheduler.due(now) == ()
    assert scheduler.due(now + timedelta(seconds=1)) == (proposal, later)


def test_canonical_promotion_requires_reviewed_base_hash():
    world, canonical_id, trial_id, run, actor_id, _ = ids()
    store = InMemoryStateStore()
    canonical = BranchState(world, canonical_id, BranchKind.CANONICAL)
    store.add(canonical)
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.HUMAN,
        display_name="GM",
        capabilities=frozenset({"canonical.promote", "action.commit"}),
    )
    bus = CommandBus(store)
    bus.register(promotion_definition())
    package = ConsequencePackage(
        source_branch_id=trial_id,
        expected_canonical_hash=canonical.state_hash,
        deltas=(StateDelta(projection="economy", operation="SET", values={"tax": 15}),),
        review_note="Approved after scenario review",
    )
    receipt = bus.execute(
        CommandProposal(
            command_type="kernel.branch.promote",
            world_id=world,
            branch_id=canonical_id,
            run_id=run,
            actor_id=actor_id,
            parameters=package.model_dump(mode="json"),
            idempotency_key="promote",
        ),
        actor,
    )
    assert receipt.result.result["promoted_delta_count"] == 1
    assert canonical.projections["economy"]["singleton"]["tax"] == 15

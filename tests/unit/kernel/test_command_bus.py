import uuid

import pytest

from domains.tabletop.onboarding import command_definition
from kernel.command_bus import CommandBus
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal
from kernel.errors import AuthorizationDenied
from kernel.state import BranchState, InMemoryStateStore

pytestmark = pytest.mark.unit


def test_trial_mutation_cannot_change_canonical_state():
    world_id, canonical_id, trial_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    actor_id, entity_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    states = InMemoryStateStore()
    canonical = BranchState(
        world_id, canonical_id, BranchKind.CANONICAL, {"tabletop.onboarding": {}}
    )
    states.add(canonical)
    trial = states.create_trial(canonical_id, trial_id)
    before = canonical.state_hash
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        display_name="test player",
        capabilities=frozenset({"action.propose", "entity.act"}),
        controlled_entity_ids=frozenset({entity_id}),
    )
    bus = CommandBus(states)
    bus.register(command_definition())
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world_id,
        branch_id=trial_id,
        run_id=run_id,
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        parameters={"action": "START"},
        idempotency_key="first",
    )
    bus.execute(proposal, actor)
    assert canonical.state_hash == before
    assert trial.state_hash != before


def test_command_authorization_is_deny_by_default():
    world_id, branch_id = uuid.uuid4(), uuid.uuid4()
    states = InMemoryStateStore()
    states.add(BranchState(world_id, branch_id, BranchKind.TRIAL))
    bus = CommandBus(states)
    bus.register(command_definition())
    actor = Actor(kind=ActorKind.AGENT, display_name="underprivileged")
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world_id,
        branch_id=branch_id,
        run_id=uuid.uuid4(),
        actor_id=actor.actor_id,
        embodied_entity_id=uuid.uuid4(),
        parameters={"action": "START"},
        idempotency_key="denied",
    )
    with pytest.raises(AuthorizationDenied):
        bus.execute(proposal, actor)


def test_proposal_only_actor_cannot_mutate_canonical_branch():
    world_id, branch_id = uuid.uuid4(), uuid.uuid4()
    actor_id, entity_id = uuid.uuid4(), uuid.uuid4()
    states = InMemoryStateStore()
    canonical = BranchState(world_id, branch_id, BranchKind.CANONICAL, {"tabletop.onboarding": {}})
    states.add(canonical)
    bus = CommandBus(states)
    bus.register(command_definition())
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        display_name="proposal-only agent",
        capabilities=frozenset({"action.propose", "entity.act"}),
        controlled_entity_ids=frozenset({entity_id}),
    )
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world_id,
        branch_id=branch_id,
        run_id=uuid.uuid4(),
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        parameters={"action": "START"},
        idempotency_key="canonical-denied",
    )
    before = canonical.state_hash

    with pytest.raises(AuthorizationDenied, match="action.commit"):
        bus.execute(proposal, actor)

    assert canonical.state_hash == before


def test_commit_capability_allows_valid_canonical_command():
    world_id, branch_id = uuid.uuid4(), uuid.uuid4()
    actor_id, entity_id = uuid.uuid4(), uuid.uuid4()
    states = InMemoryStateStore()
    canonical = BranchState(world_id, branch_id, BranchKind.CANONICAL, {"tabletop.onboarding": {}})
    states.add(canonical)
    bus = CommandBus(states)
    bus.register(command_definition())
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.HUMAN,
        display_name="committing operator",
        capabilities=frozenset({"action.propose", "action.commit", "entity.act"}),
        controlled_entity_ids=frozenset({entity_id}),
    )
    proposal = CommandProposal(
        command_type="tabletop.onboarding.act",
        world_id=world_id,
        branch_id=branch_id,
        run_id=uuid.uuid4(),
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        parameters={"action": "START"},
        idempotency_key="canonical-allowed",
    )

    receipt = bus.execute(proposal, actor)

    assert receipt.result.accepted is True
    assert canonical.version == 1

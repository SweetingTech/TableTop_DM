from __future__ import annotations

import uuid

import pytest

from kernel.contracts import BranchKind, CommandProposal, CommandResult
from kernel.event_factory import EventFactory
from kernel.perception_contracts import NON_SENSORY_TAGS
from kernel.state import BranchState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("tag", sorted(NON_SENSORY_TAGS))
def test_operator_event_never_invokes_a_physical_builder_or_resolver(tag):
    class UnexpectedResolver:
        def resolve(self, **kwargs):
            raise AssertionError("operator records must never reach physical audience resolution")

    def unexpected_builder(*args):
        raise AssertionError("operator records must never emit physical evidence")

    state = BranchState(
        world_id=uuid.uuid4(), branch_id=uuid.uuid4(), kind=BranchKind.CANONICAL, projections={}
    )
    proposal = CommandProposal(
        world_id=state.world_id,
        branch_id=state.branch_id,
        run_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        command_type="test.director",
        idempotency_key="private-direction",
    )
    result = CommandResult(result={"note": "PRIVATE_CORRECTION"}, domain_tags=(tag,))
    output = EventFactory(UnexpectedResolver()).materialize(
        proposal=proposal,
        result=result,
        before=state,
        after=state,
        emission_builder=unexpected_builder,
    )
    assert output.perceptions == () and output.event.observed_by == ()
    assert output.event.visible_to == (proposal.actor_id,)

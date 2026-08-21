import uuid

import pytest

from cognition.engine import SubjectiveStatePipeline
from cognition.models import MindState, RelationshipVector, RuntimeAssignment
from cognition.perception import PerceptionProfile
from cognition.store import MindStore
from kernel.contracts import EventEnvelopeV2
from kernel.perception_contracts import PerceptionGrant

pytestmark = pytest.mark.unit


def test_mind_store_persists_subjective_state_without_changing_event_truth():
    entity_id, actor_id = uuid.uuid4(), uuid.uuid4()
    event = EventEnvelopeV2(
        world_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        actor_id=actor_id,
        embodied_entity_id=entity_id,
        event_type="tabletop.social.rumor",
        payload={
            "claims": [
                {
                    "subject_type": "npc",
                    "predicate": "loyal",
                    "value": False,
                }
            ]
        },
        visible_to=(actor_id,),
        observed_by=(actor_id,),
        correlation_id=uuid.uuid4(),
    )
    before = event.model_copy(deep=True)
    update = SubjectiveStatePipeline().process(
        event,
        PerceptionProfile(observer_entity_id=entity_id, observer_actor_id=actor_id),
        grant=PerceptionGrant(
            event_id=event.event_id,
            world_id=event.world_id,
            branch_id=event.branch_id,
            observer_entity_id=entity_id,
            modalities=("SOUND",),
            outcome="DIRECT",
            confidence=1,
            resolver_version="test-resolver-1.0.0",
            spatial_context_hash="0" * 64,
        ),
    )
    store = MindStore()
    store.initialize(MindState(entity_id=entity_id))
    state = store.apply_subjective_update(entity_id, update)
    assert event == before
    assert state.memories
    assert store.inspect(entity_id)["observations"]


def test_mind_store_keeps_same_entity_isolated_between_branches():
    entity_id, target_id = uuid.uuid4(), uuid.uuid4()
    canonical, trial = uuid.uuid4(), uuid.uuid4()
    store = MindStore()
    store.restore(
        MindState(entity_id=entity_id, mood="CALM"),
        branch_id=canonical,
        relationships=((target_id, RelationshipVector(trust=40)),),
    )
    store.restore(
        MindState(entity_id=entity_id, mood="AFRAID"),
        branch_id=trial,
        relationships=((target_id, RelationshipVector(trust=-20)),),
    )

    assert store.get(entity_id, branch_id=canonical).mood == "CALM"
    assert store.get(entity_id, branch_id=trial).mood == "AFRAID"
    assert store.relationship(entity_id, target_id, branch_id=canonical).trust == 40
    assert store.relationship(entity_id, target_id, branch_id=trial).trust == -20


def test_mind_store_runtime_assignments_are_run_scoped_and_listable():
    world_id, branch_id, entity_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first_run, second_run = uuid.uuid4(), uuid.uuid4()
    store = MindStore()
    utility = RuntimeAssignment(
        world_id=world_id,
        branch_id=branch_id,
        run_id=first_run,
        entity_id=entity_id,
        runtime_kind="UTILITY",
    )
    planner = RuntimeAssignment(
        world_id=world_id,
        branch_id=branch_id,
        run_id=second_run,
        entity_id=entity_id,
        runtime_kind="PLANNER",
        runtime_config={"max_depth": 4},
    )

    store.set_runtime_assignment(utility)
    store.set_runtime_assignment(planner)

    assert (
        store.runtime_assignment(
            world_id=world_id,
            branch_id=branch_id,
            run_id=first_run,
            entity_id=entity_id,
        )
        == utility
    )
    listed = store.list_runtime_assignments(
        world_id=world_id,
        branch_id=branch_id,
        entity_id=entity_id,
    )
    assert {item.run_id: item for item in listed} == {
        first_run: utility,
        second_run: planner,
    }

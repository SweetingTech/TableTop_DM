from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from cognition.context import CharacterContext
from cognition.conversation import due_reply
from cognition.engine import DecisionAction
from cognition.models import Observation
from cognition.recovery import CharacterStalled, RecoveryConstraints, progress_constraints
from kernel.contracts import CommandProposal, CommandResult, EventEnvelopeV2
from kernel.control import ControllerState
from kernel.replay import ReplayRecord
from tests.unit.cognition.test_character_context import fixture_context

pytestmark = pytest.mark.unit


@pytest.fixture
def character():
    scene, actor, event, _, _ = fixture_context()
    context = CharacterContext(scene=scene, observations=(), memories=(), beliefs=())
    controller = ControllerState(
        world_id=scene.world_id,
        branch_id=scene.branch_id,
        run_id=event.run_id,
        entity_id=scene.observer_entity_id,
        owner_actor_id=actor,
        executor_actor_id=uuid.uuid4(),
        epoch=2,
        step=4,
        mode="AUTONOMOUS",
    )
    return controller, context


def committed(controller, step, action, result, **parameters):
    return ReplayRecord(
        proposal=CommandProposal(
            world_id=controller.world_id,
            branch_id=controller.branch_id,
            run_id=controller.run_id,
            embodied_entity_id=controller.entity_id,
            actor_id=controller.executor_actor_id,
            control_epoch=controller.epoch,
            control_step=step,
            decision_authorship="CHARACTER_POLICY",
            command_type=action,
            idempotency_key=f"committed-{step}",
            parameters=parameters,
        ),
        result=CommandResult(result=result),
        expected_state_hash="fixture",
    )


def test_movement_avoids_a_proven_cycle_and_keeps_other_plan_actions(character):
    control, context = character
    move = "tabletop.spatial.move"
    history = tuple(
        committed(control, index, move, {"destination": {"x": x, "y": 2}, "zone_id": "world"})
        for index, x in enumerate((2, 1, 2, 1))
    )
    east = DecisionAction(action="east", command_type=move, parameters={"dx": 1, "dy": 0})
    north = DecisionAction(action="north", command_type=move, parameters={"dx": 0, "dy": -1})
    constraints = progress_constraints(control, context, history, None, {}.get)
    eligible, receipt = constraints.eligible((east, north))
    assert eligible == (north,) and receipt is not None
    assert receipt.reasons == ("no_movement_progress",) and receipt.skipped_actions == ("east",)
    with pytest.raises(CharacterStalled, match="no_movement_progress"):
        constraints.eligible((east,))
    assert (
        progress_constraints(
            control.model_copy(update={"epoch": 3}), context, history, None, {}.get
        )
        == RecoveryConstraints()
    )


def test_attack_recovery_requires_three_recent_zero_damage_attempts_at_the_same_threat(character):
    control, context = character
    attack = "tabletop.combat.attack"
    threat = str(uuid.uuid4())
    attempts = tuple(
        committed(control, index, attack, {"damage": 0}, target_id=threat) for index in range(1, 4)
    )
    candidate = DecisionAction(
        action="strike", command_type=attack, parameters={"target_id": threat}
    )
    constraints = progress_constraints(control, context, attempts, None, {}.get)
    assert constraints.blocked(candidate) == "repeated_ineffective_attack"
    assert (
        constraints.blocked(
            candidate.model_copy(update={"parameters": {"target_id": str(uuid.uuid4())}})
        )
        is None
    )
    progressed = (*attempts[:2], committed(control, 3, attack, {"damage": 1}, target_id=threat))
    assert (
        progress_constraints(control, context, progressed, None, {}.get).blocked(candidate) is None
    )


def test_conversation_budget_requires_four_same_run_witnessed_turns(character):
    control, context = character
    now = datetime.now(UTC) + timedelta(seconds=1)
    conversation = uuid.uuid4()
    speaker = uuid.uuid4()
    events: dict[uuid.UUID, EventEnvelopeV2] = {}
    observations = []
    parent = None
    for index in range(4):
        body = control.entity_id if index % 2 == 0 else speaker
        event = EventEnvelopeV2(
            world_id=control.world_id,
            branch_id=control.branch_id,
            run_id=control.run_id,
            actor_id=uuid.uuid4(),
            embodied_entity_id=body,
            event_type="tabletop.dialogue.speak",
            visible_to=(control.executor_actor_id,),
            correlation_id=conversation,
            causation_id=parent,
        )
        parent = event.event_id
        events[event.event_id] = event
        observations.append(
            Observation(
                observer_entity_id=control.entity_id,
                source_event_id=event.event_id,
                perceived_payload={"text": "Follow the road?", "speaker_entity_id": str(body)},
                confidence=1,
                observed_at=now,
            )
        )
    context = context.model_copy(update={"observations": tuple(observations)})
    schedule = due_reply(context, control, events.get, now=now)
    assert schedule is not None
    assert progress_constraints(control, context, (), schedule, events.get).conversation_loop
    narrow = context.model_copy(update={"observations": tuple(observations[1:])})
    assert not progress_constraints(control, narrow, (), schedule, events.get).conversation_loop
    event = events[observations[0].source_event_id]
    events[event.event_id] = event.model_copy(update={"run_id": uuid.uuid4()})
    assert not progress_constraints(control, context, (), schedule, events.get).conversation_loop

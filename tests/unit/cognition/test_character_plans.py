from __future__ import annotations

import uuid

import pytest

from cognition.character_plans import select_character_plan
from cognition.context import CharacterContext
from cognition.engine import DecisionAction
from cognition.models import Observation
from domains.tabletop.spatial.scene import PerceivedEntity, PerceivedScene, SceneCoordinate
from kernel.control import ControllerState

pytestmark = pytest.mark.unit


@pytest.fixture
def recovery_scene():
    body_id = uuid.uuid4()
    attacker_id = uuid.uuid4()
    control = ControllerState(
        world_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        entity_id=body_id,
        owner_actor_id=uuid.uuid4(),
        executor_actor_id=uuid.uuid4(),
        epoch=1,
        mode="AUTONOMOUS",
    )
    body = PerceivedEntity(
        entity_id=body_id,
        position=SceneCoordinate(x=0, y=0),
        position_confidence=1,
        knowledge_state="VISIBLE",
        detail_level="INSPECTED",
        health=4,
        max_health=12,
        mana=4,
    )
    attacker = body.model_copy(
        update={"entity_id": attacker_id, "position": SceneCoordinate(x=1, y=0)}
    )
    scene = PerceivedScene(
        observer_entity_id=body_id,
        world_id=control.world_id,
        branch_id=control.branch_id,
        projection_version=4,
        visible_zones=("world",),
        perceived_entities=(body, attacker),
        recent_observations=(),
        available_viewpoints=(),
    )
    context = CharacterContext(
        scene=scene,
        observations=(
            Observation(
                observer_entity_id=body_id,
                source_event_id=uuid.uuid4(),
                perceived_payload={"attacker_id": str(attacker_id), "target_id": str(body_id)},
                confidence=1,
            ),
        ),
        beliefs=(),
        memories=(),
        actions=(
            DecisionAction(
                action="west", command_type="tabletop.spatial.move", parameters={"dx": -1, "dy": 0}
            ),
            DecisionAction(
                action="east", command_type="tabletop.spatial.move", parameters={"dx": 1, "dy": 0}
            ),
            DecisionAction(
                action="heal",
                command_type="tabletop.magic.invoke",
                parameters={"spell_id": "MEND", "target_id": str(body_id)},
            ),
        ),
    )
    return control, context


@pytest.mark.parametrize(
    ("health", "attacker_x", "expected"),
    [(4, 1, "ACTIVE"), (7, 1, "COMPLETED"), (4, 0, "INTERRUPTED")],
)
def test_recovery_rechecks_injury_and_threat_before_next_step(
    recovery_scene, health, attacker_x, expected
):
    control, context = recovery_scene
    initial = select_character_plan(context, control, hunger=20, fatigue=30, previous=None)
    assert initial is not None
    assert initial.allowed_actions == ("west",)
    assert initial.plan.action == "WITHDRAW"
    assert initial.plan.needs.hunger == 20 and initial.plan.needs.fatigue == 30

    body, attacker = context.scene.perceived_entities
    body = body.model_copy(update={"position": SceneCoordinate(x=-1, y=0), "health": health})
    attacker = attacker.model_copy(update={"position": SceneCoordinate(x=attacker_x, y=0)})
    current_scene = context.scene.model_copy(update={"perceived_entities": (body, attacker)})
    refreshed = context.model_copy(update={"scene": current_scene})
    committed_step = uuid.uuid4()
    next_step = control.model_copy(update={"step": 1})
    result = select_character_plan(
        refreshed, next_step, hunger=25, fatigue=35, previous=(initial.plan, committed_step)
    )
    assert result is not None
    assert result.plan.status == expected
    assert result.plan.plan_id == initial.plan.plan_id
    assert result.plan.source_command_id == committed_step
    assert result.plan.completed_steps == 1
    assert result.plan.needs.health == health
    if expected == "ACTIVE":
        assert result.plan.action == "MEND" and result.allowed_actions == ("heal",)
    else:
        assert result.plan.action is None and not result.allowed_actions
        assert result.plan.cooldown_until_step == 3
        during_cooldown = select_character_plan(
            context,
            next_step.model_copy(update={"step": 2}),
            hunger=25,
            fatigue=35,
            previous=(result.plan, uuid.uuid4()),
        )
        assert during_cooldown is not None
        assert during_cooldown.plan.status == expected and not during_cooldown.allowed_actions

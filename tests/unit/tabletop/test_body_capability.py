from __future__ import annotations

import uuid

import pytest

from cognition.store import MindStore
from domains.tabletop.character_actions import character_action_candidates
from domains.tabletop.spatial.service import build_perceived_scene
from kernel.errors import BodySleeping
from tests.unit.kernel.test_action_randomness import arena
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import setup_scene

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("race", [False, True])
def test_stand_in_preserves_budget_while_incapacitated_including_commit_race(
    monkeypatch, tmp_path, race
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 2,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    sim, runner = app.extensions["simulation"], app.extensions["character_runner"]

    def body():
        return sim.states.get(uuid.UUID(base["branch_id"])).projections["tabletop.entities"][
            card["entity_id"]
        ]

    original = runner.decisions.decide
    if race:

        def become_stunned(*args, **kwargs):
            receipt = original(*args, **kwargs)
            body()["conditions"] = ["stunned"]
            return receipt

        monkeypatch.setattr(runner.decisions, "decide", become_stunned)
    else:
        body()["conditions"] = ["stunned"]
    for _ in range(5):
        assert runner.run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["mode"] == "AUTONOMOUS" and control["step"] == control["failures"] == 0
    monkeypatch.setattr(runner.decisions, "decide", original)
    body()["conditions"] = []
    assert runner.run_once() == 1


def test_self_scene_suppresses_incapacitated_choices_without_revealing_other_conditions(tmp_path):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    state.projections["tabletop.entities"][str(request.embodied_entity_id)]["conditions"] = [
        "stunned"
    ]
    state.projections["tabletop.entities"][request.parameters["target_id"]]["conditions"] = [
        "paralyzed"
    ]
    scene = build_perceived_scene(
        app,
        MindStore(),
        world_id=request.world_id,
        branch_id=request.branch_id,
        observer_entity_id=request.embodied_entity_id,
        actor_id=actor.actor_id,
    )
    own = next(
        row for row in scene.perceived_entities if row.entity_id == request.embodied_entity_id
    )
    other = next(
        row
        for row in scene.perceived_entities
        if str(row.entity_id) == request.parameters["target_id"]
    )
    assert own.status == "INCAPACITATED" and other.status != "INCAPACITATED"
    assert character_action_candidates(scene, actor=actor, branch_kind=state.kind) == ()


@pytest.mark.parametrize(
    "condition",
    [
        {"hp": 0},
        {"defeated": True},
        {"conditions": ["StUnNeD"]},
        {"conditions": ["unconscious"]},
        {"conditions": ["paralyzed"]},
        {"status": "DEAD"},
        {"dead": True},
        {"conditions": ["dead"]},
    ],
)
@pytest.mark.parametrize(
    "command,parameters",
    [
        ("tabletop.spatial.move", {"dx": 0, "dy": 1}),
        ("tabletop.dialogue.speak", {"text": "I should not be speaking."}),
        ("tabletop.combat.guard", {}),
    ],
)
def test_incapacitated_bodies_cannot_move_speak_or_guard(tmp_path, condition, command, parameters):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    body = state.projections["tabletop.entities"][str(request.embodied_entity_id)]
    body.update(condition)
    before = state.state_hash
    with pytest.raises(ValueError, match="capable"):
        app.bus.execute(
            request.model_copy(update={"command_type": command, "parameters": parameters}), actor
        )
    assert state.version == 0 and state.state_hash == before


@pytest.mark.parametrize("command", ["tabletop.combat.attack", "tabletop.magic.invoke"])
def test_human_can_wake_by_valid_combat_but_policy_waits(tmp_path, command):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    body = state.projections["tabletop.entities"][str(request.embodied_entity_id)]
    body.update({"asleep": True, "mana": 4})
    parameters = dict(request.parameters)
    if command.endswith("invoke"):
        parameters["spell_id"] = "ARCANE_BOLT"
    request = request.model_copy(update={"command_type": command, "parameters": parameters})
    before = state.state_hash
    with pytest.raises(BodySleeping):
        app.bus.definition(command).handler(
            request.model_copy(update={"decision_authorship": "CHARACTER_POLICY"}), state
        )
    assert state.version == 0 and state.state_hash == before
    receipt = app.bus.execute(request, actor)
    assert not state.projections["tabletop.entities"][str(request.embodied_entity_id)]["asleep"]
    assert app.bus.execute(request, actor) == receipt and state.version == 1


def test_failed_human_action_does_not_wake_or_spend_resources(tmp_path):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    state.projections["tabletop.entities"][str(request.embodied_entity_id)]["asleep"] = True
    before = state.state_hash
    with pytest.raises(ValueError):
        app.bus.execute(
            request.model_copy(update={"parameters": {"target_id": str(uuid.uuid4())}}), actor
        )
    assert state.state_hash == before and state.version == 0


@pytest.mark.parametrize("marker", [{"status": "DEAD"}, {"dead": True}, {"conditions": ["dead"]}])
def test_mend_cannot_resurrect_dead_target_with_stale_positive_hp(tmp_path, marker):
    app, actor, request = arena(tmp_path)
    state = app.states.get(request.branch_id)
    body = state.projections["tabletop.entities"][str(request.embodied_entity_id)]
    body["mana"] = 4
    state.projections["tabletop.entities"][request.parameters["target_id"]].update(
        {"hp": 5, **marker}
    )
    before = state.state_hash
    with pytest.raises(ValueError, match="capable"):
        app.bus.execute(
            request.model_copy(
                update={
                    "command_type": "tabletop.magic.invoke",
                    "parameters": {**request.parameters, "spell_id": "MEND"},
                }
            ),
            actor,
        )
    assert state.state_hash == before and state.version == 0

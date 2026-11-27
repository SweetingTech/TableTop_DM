from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_npc_goals import clock_path, configure_subjective
from tests.unit.kernel.test_party_api import create_and_invite, party_scene
from tests.unit.kernel.test_world_time import NOW, api_command

pytestmark = pytest.mark.unit


def prepare_invited_resident(app, game=None, *, curious=False, max_steps=1, human_owner=False):
    game, _, resident_path, _, _ = configure_subjective(app, game, curious=curious)
    admin, player, player_card, player_path, run, resident, base = game
    party_id, invite_id = create_and_invite(game)
    context = admin.get(resident_path + "/context", query_string={"run_id": run})
    assert context.status_code == 200, context.get_json()
    situation = context.get_json()["situation"]
    assert situation["party_invitations"][0]["motive"] == "CARE"
    assert invite_id not in str(situation)
    assert "PRIVATE_NPC_VOW" not in str(party_scene(player, player_path))
    if human_owner:
        assert player.get(resident_path + "/scene").status_code == 403
        owner = player.get("/api/v2/auth/session").get_json()["user"]["actor_id"]
        api_command(
            admin,
            base,
            "tabletop.entity.set_controllers",
            {"changes": [{"entity_id": resident, "controller_actor_id": owner}]},
            "authorize-resident-player",
        )

    clock = admin.get(clock_path(base)).get_json()["clock"]
    executor = admin.post(
        "/api/v2/actors",
        json={
            "world_id": base["world_id"],
            "display_name": "Resident routine clock",
            "kind": "AGENT",
            "capabilities": ["world.read", "action.propose", "action.commit", "mind.read.all"],
        },
    )
    assert executor.status_code == 201, executor.get_json()
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": clock["epoch"],
            "executor_actor_id": executor.get_json()["actor_id"],
            "paused": False,
            "seconds_per_tick": 6,
            "wall_time": NOW.isoformat(),
        },
        "resume-for-party-response",
    )
    response = admin.post(
        resident_path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": max_steps,
            "interval_ms": 100,
            "idempotency_key": "resident-controller",
        },
    )
    assert response.status_code == 200, response.get_json()
    return game, resident_path, party_id, invite_id


def assert_resident_response(app, base, resident, invite_id, *, accept):
    runner = app.extensions["character_runner"]
    (controller,) = runner.controllers.due()
    decision = runner.decisions.decide(
        controller.scope, controller.executor_actor_id, controller.decision_key, controller
    )
    assert decision.outcome.proposal.command_type == "tabletop.party.respond", [
        (candidate.action, candidate.factors, candidate.score)
        for candidate in decision.outcome.trace.candidates
    ]
    assert runner.run_once() == 1
    source = runner.snapshot()
    branch_id = uuid.UUID(base["branch_id"])
    committed = source.command_history[branch_id][-1]
    assert committed.proposal.command_type == "tabletop.party.respond"
    assert committed.proposal.input_origin == "NPC_POLICY"
    assert str(committed.proposal.embodied_entity_id) == resident
    assert str(committed.proposal.parameters["invitation_id"]) == invite_id
    assert committed.result.result["kind"] == ("JOINED" if accept else "DECLINED")
    assert runner.run_once() == 0


@pytest.mark.parametrize("curious", [False, True])
def test_resident_responds_from_pinned_motives(monkeypatch, tmp_path, curious):
    monkeypatch.setenv("TTDM_LLM_MODE", "mock")
    app = _app(monkeypatch, tmp_path)
    game, resident_path, party_id, invite_id = prepare_invited_resident(app, curious=curious)
    _, player, card, player_path, _, resident, base = game
    assert_resident_response(app, base, resident, invite_id, accept=not curious)
    party = party_scene(player, player_path)["parties"][0]
    assert party["party_id"] == party_id
    assert party["member_ids"] == (
        [card["entity_id"]] if curious else [card["entity_id"], resident]
    )
    assert player.get(resident_path + "/scene").status_code == 403

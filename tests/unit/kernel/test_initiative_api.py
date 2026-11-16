from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from domains.tabletop.action_time import wait_seconds
from domains.tabletop.initiative import ENCOUNTERS
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance
from tests.unit.kernel.test_world_time import NOW, api_command, clock_game

pytestmark = pytest.mark.unit


def start_encounter(app, game=None):
    game = game or clock_game(app)
    admin, player, card, path, run, target, base = game
    receipt = api_command(
        admin,
        base,
        "tabletop.encounter.start",
        {"participants": [card["entity_id"], target]},
        "initiative",
    )
    state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    return game, state, receipt


def ordered(receipt):
    return [row["entity_id"] for row in receipt["result"]["result"]["order"]]


def controller(game, entity_id):
    return game[1] if entity_id == game[2]["entity_id"] else game[0]


def test_seeded_order_readiness_retry_and_scene_privacy(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    first, second = ordered(receipt)
    assert wait_seconds(state, uuid.UUID(first)) == 0
    assert wait_seconds(state, uuid.UUID(second)) == 6
    row = receipt["result"]["result"]
    saved = state.projections[ENCOUNTERS][row["encounter_id"]]
    assert saved["run_id"] == base["run_id"] and saved["order"] == row["order"]
    assert (
        state.projections["tabletop.entities"][card["entity_id"]]["ability_scores"]
        == card["ability_scores"]
    )
    assert all(item["total"] == item["roll"] + item["bonus"] for item in row["order"])
    assert row["randomness"]["branch_sequence"] > 0
    before = state.version, state.state_hash
    retry = api_command(
        admin,
        base,
        "tabletop.encounter.start",
        {"participants": [target, card["entity_id"]]},
        "initiative",
    )
    assert retry == receipt
    assert (state.version, state.state_hash) == before
    scene = player.get(path + "/scene").get_json()
    own = next(
        item for item in scene["perceived_entities"] if item["entity_id"] == card["entity_id"]
    )
    other = next(item for item in scene["perceived_entities"] if item["entity_id"] == target)
    assert own["action_wait_seconds"] == (0 if first == card["entity_id"] else 6)
    assert other["action_wait_seconds"] is None
    for private in (
        "encounter_id",
        "branch_sequence",
        "source_command_id",
        "tabletop-initiative",
        "action_seed",
    ):
        assert private not in str(scene)


def test_turn_windows_deny_out_of_turn_and_keep_offscreen_world_moving(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    first, second = ordered(receipt)
    before = state.version, state.state_hash
    assert (
        command(
            controller(game, second),
            base,
            {"entity_id": second},
            "tabletop.combat.guard",
            {},
            "early",
        ).status_code
        == 400
    )
    assert (state.version, state.state_hash) == before
    assert (
        command(
            controller(game, first),
            base,
            {"entity_id": first},
            "tabletop.combat.guard",
            {},
            "first",
        ).status_code
        == 200
    )
    advance_clock(admin, base, 5)
    assert wait_seconds(state, uuid.UUID(second)) == 1
    advance_clock(admin, base, 6)
    assert wait_seconds(state, uuid.UUID(first)) == 6
    assert (
        command(
            controller(game, second),
            base,
            {"entity_id": second},
            "tabletop.combat.guard",
            {},
            "second",
        ).status_code
        == 200
    )
    # Both participants may miss later windows; the canonical clock still advances.
    advance_clock(admin, base, 120)
    assert wait_seconds(state, uuid.UUID(first)) == 0
    assert state.projections["tabletop.clock"]["singleton"]["seconds"] == 120


def test_overlapping_forged_and_player_configured_initiative_do_not_write(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    before = state.version, state.state_hash
    for client, params, expected in [
        (admin, {"participants": [card["entity_id"], target]}, 400),
        (admin, {"participants": [card["entity_id"], target], "order": [target]}, 400),
        (admin, {"participants": [card["entity_id"], card["entity_id"]]}, 400),
        (admin, {"participants": [card["entity_id"], str(uuid.uuid4())]}, 400),
        (player, {"participants": [card["entity_id"], target]}, 403),
    ]:
        response = client.post(
            "/api/v2/commands",
            json={
                **base,
                "command_type": "tabletop.encounter.start",
                "parameters": params,
                "idempotency_key": str(uuid.uuid4()),
            },
        )
        assert response.status_code == expected, response.get_json()
        assert (state.version, state.state_hash) == before
    assert (
        command(player, base, card, "tabletop.rest.start", {"kind": "LONG"}, "rest").status_code
        == 400
    )
    assert (state.version, state.state_hash) == before


def test_ending_encounter_removes_turn_wait_without_refunding_action_cost(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    first, second = ordered(receipt)
    assert (
        command(
            controller(game, first),
            base,
            {"entity_id": first},
            "tabletop.combat.guard",
            {},
            "guard",
        ).status_code
        == 200
    )
    stop = {"encounter_id": receipt["result"]["result"]["encounter_id"]}
    api_command(admin, base, "tabletop.encounter.stop", stop, "end")
    assert wait_seconds(state, uuid.UUID(first)) == 6
    assert wait_seconds(state, uuid.UUID(second)) == 0
    before = state.version, state.state_hash
    repeat = api_command(admin, base, "tabletop.encounter.stop", stop, "end")
    assert repeat["result"]["result"]["active"] is False
    assert (state.version, state.state_hash) == before


def test_clock_partition_preserves_turns_work_and_guard_expiry(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    whole, split = state.working_copy(), state.working_copy()
    projected_advance(whole, 25)
    for end in (5, 6, 7, 12, 24, 25):
        projected_advance(split, end)
    assert physical_projection(whole) == physical_projection(split)
    first = ordered(receipt)[0]
    assert wait_seconds(whole, uuid.UUID(first)) == wait_seconds(split, uuid.UUID(first)) == 0
    # The target's existing gardening only accrues its available initiative windows.
    assert whole.projections["tabletop.entities"][target]["weeded_units"] == (
        13 if target == first else 12
    )


def test_concurrent_same_turn_actions_commit_once_and_retry_original_receipt(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    first = ordered(receipt)[0]

    def submit(key):
        client = app.test_client()
        selected = controller(game, first)
        client.environ_base.update(selected.environ_base)
        cookie = selected.get_cookie("ttdm_session")
        if cookie:
            client.set_cookie("ttdm_session", cookie.value)
        return command(client, base, {"entity_id": first}, "tabletop.combat.guard", {}, key)

    with ThreadPoolExecutor(max_workers=2) as workers:
        duplicate = list(workers.map(submit, ["same", "same"]))
    assert [item.status_code for item in duplicate] == [200, 200]
    assert duplicate[0].get_json() == duplicate[1].get_json()
    before = state.version, state.state_hash
    assert submit("new").status_code == 400
    assert (state.version, state.state_hash) == before


@pytest.mark.parametrize("actor_kind", ["HUMAN", "AGENT"])
def test_same_typed_initiative_enforcement_for_human_and_agent_trials(actor_kind):
    from kernel.contracts import ActorKind
    from kernel.errors import BodyActionPending
    from tests.unit.tabletop.test_domain_commands import domain as domain_fixture
    from tests.unit.tabletop.test_domain_commands import proposal

    domain = domain_fixture.__wrapped__()
    actor = domain["actor"].model_copy(
        update={
            "kind": ActorKind(actor_kind),
            "controlled_entity_ids": frozenset({domain["hero"], domain["enemy"]}),
        }
    )
    state = domain["state"]
    state.projections["tabletop.clock"] = {
        "singleton": {"run_id": str(domain["run"]), "seconds": 0}
    }
    first = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.encounter.start",
            {"participants": [domain["hero"], domain["enemy"]]},
            "start",
            seed=14,
        ),
        actor,
    )
    ids = [row["entity_id"] for row in first.result.result["order"]]
    pending = proposal(domain, "tabletop.combat.guard", {}, "too-early").model_copy(
        update={"embodied_entity_id": uuid.UUID(ids[1])}
    )
    mark = state.state_hash, state.version
    with pytest.raises(BodyActionPending):
        domain["bus"].execute(pending, actor)
    assert (state.state_hash, state.version) == mark
    ready = pending.model_copy(
        update={
            "command_id": uuid.uuid4(),
            "idempotency_key": "ready",
            "embodied_entity_id": uuid.UUID(ids[0]),
        }
    )
    receipt = domain["bus"].execute(ready, actor)
    assert domain["bus"].execute(ready, actor) == receipt


def test_autonomous_runner_waits_without_budget_loss_then_acts_in_window(monkeypatch, tmp_path):
    from tests.unit.kernel.test_action_time_api import clock_path

    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    # Put the actual player body in its opponent's window, irrespective of seeded order.
    player_index = ordered(receipt).index(card["entity_id"])
    blocked_at = 6 if player_index == 0 else 0
    if blocked_at:
        advance_clock(admin, base, blocked_at)
    current = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": current["executor_actor_id"],
            "wall_time": NOW.isoformat(),
            "paused": False,
            "seconds_per_tick": 6,
        },
        "resume",
    )
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 1,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200, response.get_json()
    runner = app.extensions["character_runner"]
    for _ in range(3):
        assert runner.run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["step"] == control["failures"] == 0 and control["mode"] == "AUTONOMOUS"
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=1)) == 1
    assert runner.run_once() == 1


def test_outsiders_cannot_bypass_encounter_order_and_uninvolved_work_continues(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = start_encounter(app)
    admin, player, card, path, run, target, base = game
    outsider = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": outsider,
            "entity_type": "NPC",
            "name": "Uninvolved gardener",
            "controller_actor_id": receipt["event"]["actor_id"],
            "public_state": {"hp": 12, "x": 1, "y": 1},
        },
        "outsider",
    )
    api_command(
        admin,
        base,
        "tabletop.activity.start",
        {"entity_id": outsider, "kind": "WEED", "duration_seconds": 100},
        "outsider-work",
    )
    before = state.version, state.state_hash
    response = command(
        admin,
        base,
        {"entity_id": outsider},
        "tabletop.combat.attack",
        {"target_id": target},
        "bypass",
    )
    assert response.status_code == 400
    assert (state.version, state.state_hash) == before
    advance_clock(admin, base, 25)
    assert state.projections["tabletop.entities"][outsider]["weeded_units"] == 25

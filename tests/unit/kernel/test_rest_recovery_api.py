from __future__ import annotations

import uuid

import pytest

from domains.tabletop.activities import ACTIVITIES, Activity
from domains.tabletop.rest import LONG_SECONDS, SHORT_SECONDS, recover
from kernel.contracts import ActorKind
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.tabletop.test_domain_commands import domain as domain_fixture
from tests.unit.tabletop.test_domain_commands import proposal

pytestmark = pytest.mark.unit


def prepare_rest(app, game=None):
    game = game or clock_game(app)
    admin, player, card, path, run, target, base = game
    api_command(
        admin,
        base,
        "tabletop.resources.configure",
        {"entity_id": card["entity_id"], "max_hp": 12, "max_mana": 8},
        "limits",
    )
    resources(app, admin, base, card["entity_id"], hp=2, mana=1)
    state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    return game, state


def rest(player, base, card, kind="LONG", key="rest"):
    response = command(player, base, card, "tabletop.rest.start", {"kind": kind}, key)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_real_rest_exact_boundaries_caps_card_ownership_retry_and_partition(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    receipt = rest(player, base, card)

    def body():
        return state.projections["tabletop.entities"][card["entity_id"]]

    assert body()["hp"] == 2 and body()["mana"] == 1
    whole = state.working_copy()
    projected_advance(whole, LONG_SECONDS + 100)
    advance_clock(admin, base, SHORT_SECONDS - 1)
    assert body()["hp"] == 2
    advance_clock(admin, base, SHORT_SECONDS)
    assert body()["hp"] == 5 and body()["mana"] == 1
    advance_clock(admin, base, LONG_SECONDS - 1)
    assert body()["hp"] == 5
    advance_clock(admin, base, LONG_SECONDS)
    assert body()["hp"] == 12 and body()["mana"] == 8
    assert body()["last_long_rest_seconds"] == LONG_SECONDS
    advance_clock(admin, base, LONG_SECONDS + 100)
    assert physical_projection(whole) == physical_projection(state)
    mark = state.version, state.state_hash
    again = rest(player, base, card)
    for field in ("result", "event", "state_hash"):
        assert again[field] == receipt[field]
    assert (state.version, state.state_hash) == mark
    stored = next(
        row
        for row in player.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == card["character_id"]
    )
    assert stored == card


def test_physical_action_interrupts_rest_but_speech_and_camera_do_not(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    rest(player, base, card)
    advance_clock(admin, base, 3599)
    for kind, params in [
        ("tabletop.dialogue.speak", {"text": "Keep watch."}),
        ("tabletop.battlefield.set_control_mode", {"camera_mode": "FIRST_PERSON"}),
    ]:
        response = command(player, base, card, kind, params, kind)
        assert response.status_code == 200, response.get_json()
    response = command(player, base, card, "tabletop.combat.guard", {}, "interrupt")
    assert response.status_code == 200
    row = state.projections[ACTIVITIES][card["entity_id"]]
    assert row["status"] == "CANCELLED" and "recovery" not in row["details"]
    advance_clock(admin, base, 4000)
    assert state.projections["tabletop.entities"][card["entity_id"]]["hp"] == 2


@pytest.mark.parametrize(
    "parameters",
    [
        {"kind": "SHORT", "duration_seconds": 1},
        {"kind": "SHORT", "hp": 12},
        {"kind": "SHORT", "entity_id": str(uuid.UUID(int=1))},
    ],
)
def test_forged_rest_and_player_resource_configuration_have_no_writes(
    monkeypatch, tmp_path, parameters
):
    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    before = state.version, state.state_hash
    assert (
        command(player, base, card, "tabletop.rest.start", parameters, "forge").status_code == 400
    )
    assert (
        command(
            player,
            base,
            card,
            "tabletop.resources.configure",
            {"entity_id": card["entity_id"], "max_hp": 999, "max_mana": 999},
            "forbidden",
        ).status_code
        == 403
    )
    assert (state.version, state.state_hash) == before


@pytest.mark.parametrize("body", [{"hp": 0}, {"dead": True}, {"conditions": ["stunned"]}])
def test_defeated_dead_and_incapacitated_bodies_cannot_rest(monkeypatch, tmp_path, body):
    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    state.projections["tabletop.entities"][card["entity_id"]].update(body)
    before = state.version, state.state_hash
    assert (
        command(player, base, card, "tabletop.rest.start", {"kind": "LONG"}, "no").status_code
        == 400
    )
    assert (state.version, state.state_hash) == before


def test_uninterrupted_rule_legacy_caps_long_cooldown_and_no_condition_cure():
    activity = Activity(
        activity_id=uuid.uuid4(),
        entity_id=uuid.uuid4(),
        kind="SLEEP",
        duration_seconds=86400,
        started_seconds=0,
        updated_seconds=0,
        origin={},
    )
    body = {"hp": 2, "mana": 1, "conditions": ["poisoned"]}
    first = recover(activity, body, 0, 28800, allowed=True)
    assert body["hp"] == 2 and body["mana"] == 1
    body.update(max_hp=12, max_mana=8)
    recover(activity, body, 28800, 57600, allowed=True)
    assert body["hp"] == 5 and body["mana"] == 1  # long recovery still on cooldown
    recover(activity, body, 86400, 115200, allowed=True)
    assert body["hp"] == 12 and body["mana"] == 8
    assert body["conditions"] == ["poisoned"]
    interrupted = recover(first, body, 28800, 28801, allowed=False)
    assert "recovery" not in interrupted.details


def test_real_damage_interrupts_rest_atomically(monkeypatch, tmp_path):
    from tests.unit.kernel.test_death_recovery_api import healer

    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    resources(app, admin, base, card["entity_id"], hp=8, mana=1)
    client, attacker = healer(app, game)
    resources(app, admin, base, attacker["entity_id"], known_spells=("ARCANE_BOLT",))
    rest(player, base, card)
    advance_clock(admin, base, 3599)
    damaged = command(
        client,
        base,
        attacker,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": card["entity_id"]},
        "damage",
    )
    assert damaged.status_code == 200, damaged.get_json()
    assert state.projections[ACTIVITIES][card["entity_id"]]["status"] == "CANCELLED"
    advance_clock(admin, base, 3600)
    assert state.projections["tabletop.entities"][card["entity_id"]]["hp"] == 5


@pytest.mark.parametrize("life", [False, True])
def test_offscreen_npc_rest_and_sleep_share_recovery_and_partition_rules(
    monkeypatch, tmp_path, life
):
    from tests.unit.kernel.test_population_runtime_api import seed_routine

    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, run, target, base = game
    seed_routine(app, admin, base, target)
    resources(app, admin, base, target, hp=2, mana=1)
    api_command(
        admin,
        base,
        "tabletop.resources.configure",
        {"entity_id": target, "max_hp": 12, "max_mana": 8},
        "npc-limits",
    )
    params = {
        "entity_id": target,
        "expected_version": 1,
        "work_seconds": 60,
        "rest_seconds": 28800,
        "hunger_limit": 86400,
        "fatigue_limit": 86400,
    }
    if life:
        params["life"] = {
            "home": {"x": 1, "y": 0},
            "workplace": {"x": 1, "y": 0},
            "sleep_start_seconds": 0,
            "sleep_seconds": 28800,
        }
    api_command(admin, base, "tabletop.routine.configure", params, "npc-rest")
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    whole, split = state.working_copy(), state.working_copy()
    end = 28800 if life else 28860
    projected_advance(whole, end)
    for stop in (60, 3599, 3600, 3660, 20000, end):
        projected_advance(split, stop)
    assert physical_projection(whole) == physical_projection(split)
    body = whole.projections["tabletop.entities"][target]
    assert body["hp"] == 12 and body["mana"] == 8
    assert body["last_long_rest_seconds"] == end


def test_cap_changes_do_not_refill_and_busy_rest_is_rejected(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state = prepare_rest(app)
    admin, player, card, path, run, target, base = game
    before = state.version, state.state_hash
    rejected = command(
        admin,
        base,
        card,
        "tabletop.resources.configure",
        {"entity_id": card["entity_id"], "max_hp": 1, "max_mana": 8},
        "bad-cap",
    )
    assert rejected.status_code == 400
    assert (state.version, state.state_hash) == before
    api_command(
        admin,
        base,
        "tabletop.resources.configure",
        {"entity_id": card["entity_id"], "max_hp": 20, "max_mana": 20},
        "raise-cap",
    )
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert body["hp"] == 2 and body["mana"] == 1
    assert command(player, base, card, "tabletop.combat.guard", {}, "busy").status_code == 200
    before = state.version, state.state_hash
    assert (
        command(
            player, base, card, "tabletop.rest.start", {"kind": "SHORT"}, "busy-rest"
        ).status_code
        == 400
    )
    assert (state.version, state.state_hash) == before


@pytest.mark.parametrize("kind", [ActorKind.HUMAN, ActorKind.AGENT])
def test_rest_has_identical_control_and_recovery_rules_in_trials(kind):
    domain = domain_fixture.__wrapped__()
    actor = domain["actor"].model_copy(update={"kind": kind})
    state = domain["state"]
    state.projections["tabletop.clock"] = {
        "singleton": {"run_id": str(domain["run"]), "seconds": 0}
    }
    body = state.projections["tabletop.entities"][str(domain["hero"])]
    body.update(hp=1, max_hp=12, mana=0, max_mana=4)
    request = proposal(domain, "tabletop.rest.start", {"kind": "SHORT"}, "rest")
    receipt = domain["bus"].execute(request, actor)
    assert domain["bus"].execute(request, actor) == receipt
    from domains.tabletop.activities import progress

    progress(state, 3600)
    body = state.projections["tabletop.entities"][str(domain["hero"])]
    assert body["hp"] == 4 and body["mana"] == 0

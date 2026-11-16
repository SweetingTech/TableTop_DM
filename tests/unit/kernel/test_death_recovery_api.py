from __future__ import annotations

import uuid

import pytest

from domains.tabletop.recovery import STABLE_RECOVERY_SECONDS, VITALS, VitalState, advance
from kernel.contracts import BranchKind
from kernel.state import BranchState
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command, resources
from tests.unit.kernel.test_timed_effects_api import physical_projection, projected_advance
from tests.unit.kernel.test_world_time import api_command, clock_game

pytestmark = pytest.mark.unit
BODY = uuid.UUID(int=42)


def dying(seed):
    state = BranchState(
        uuid.uuid4(),
        uuid.uuid4(),
        BranchKind.CANONICAL,
        {
            "tabletop.entities": {str(BODY): {"hp": 0, "max_hp": 12, "defeated": True}},
            VITALS: {
                str(BODY): VitalState(
                    run_id=uuid.uuid4(),
                    source_command_id=uuid.uuid4(),
                    seed=seed,
                    next_save_seconds=6,
                ).model_dump(mode="json")
            },
        },
    )
    return state, state.projections["tabletop.entities"][str(BODY)]


def test_natural_one_counts_two_failures_at_exact_six_second_boundary():
    state, body = dying(2)
    advance(state, 5)
    assert state.projections[VITALS][str(BODY)]["rolls"] == []
    advance(state, 6)
    row = state.projections[VITALS][str(BODY)]
    assert row["rolls"] == [1] and row["failures"] == 2
    assert body["hp"] == 0 and not body.get("dead")
    advance(state, 12)
    assert state.projections[VITALS][str(BODY)]["status"] == "DEAD"
    assert body["dead"] and body["hp"] == 0


def test_natural_twenty_recovers_one_health_and_preserves_independent_conditions():
    state, body = dying(13)
    body["conditions"] = ["poisoned"]
    advance(state, 6)
    assert body["hp"] == 1 and body["defeated"] is False
    assert body["conditions"] == ["poisoned"]
    assert str(BODY) not in state.projections[VITALS]


def test_three_successes_stabilize_then_recover_on_the_clock_once():
    state, body = dying(18)
    advance(state, 18)
    row = state.projections[VITALS][str(BODY)]
    assert row["rolls"] == [16, 19, 12]
    assert row["status"] == "STABLE" and not body.get("dead")
    advance(state, 18 + STABLE_RECOVERY_SECONDS - 1)
    assert body["hp"] == 0
    advance(state, 18 + STABLE_RECOVERY_SECONDS)
    assert body["hp"] == 1 and body["defeated"] is False
    advance(state, 10000)
    assert body["hp"] == 1


def test_three_failures_die_and_later_time_does_not_resurrect():
    state, body = dying(40)
    advance(state, 18)
    assert body["dead"] and state.projections[VITALS][str(BODY)]["failures"] == 3
    advance(state, 10000)
    assert body["dead"] and body["hp"] == 0


def defeat(app, game=None):
    game = game or clock_game(app)
    admin, player, card, path, run, target, base = game
    resources(app, admin, base, card["entity_id"], hp=12, mana=8)
    resources(app, admin, base, target, hp=1)
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.magic.invoke",
            "parameters": {"spell_id": "ARCANE_BOLT", "target_id": target},
            "idempotency_key": "defeat",
            "seed": 0,
        },
    )
    assert response.status_code == 200, response.get_json()
    state = app.extensions["world_runner"].snapshot().states.get(uuid.UUID(base["branch_id"]))
    return game, state, response.get_json()


def test_actual_damage_records_trusted_seed_and_retry_never_restarts_saves(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = defeat(app)
    admin, player, card, path, run, target, base = game
    row = state.projections[VITALS][target]
    assert row["seed"] == receipt["result"]["result"]["randomness"]["action_seed"] != 0
    assert row["next_save_seconds"] == 6
    advance_clock(admin, base, 5)
    before = state.state_hash, state.version
    repeated = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": target},
        "defeat",
    )
    for field in ("result", "event", "state_hash"):
        assert repeated.get_json()[field] == receipt[field]
    assert (state.state_hash, state.version) == before
    assert state.projections[VITALS][target]["next_save_seconds"] == 6
    whole, split = state.working_copy(), state.working_copy()
    projected_advance(whole, 4000)
    for end in (6, 12, 18, 24, 30, 3606, 4000):
        projected_advance(split, end)
    assert physical_projection(whole) == physical_projection(split)
    assert state.projections["tabletop.entities"][target]["hp"] == 0


def healer(app, game):
    admin, player, card, path, run, target, base = game
    simulation = app.extensions["world_runner"].snapshot()
    actor = simulation.entities[
        (uuid.UUID(base["branch_id"]), uuid.UUID(target))
    ].controller_actor_id
    assert actor is not None
    entity = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": entity,
            "name": "Rescuer",
            "entity_type": "NPC",
            "controller_actor_id": str(actor),
            "public_state": {
                "hp": 12,
                "max_hp": 12,
                "mana": 8,
                "x": 0,
                "y": 1,
                "zone_id": "world",
                "known_spells": ["MEND"],
            },
        },
        "rescuer",
    )
    return admin, {"entity_id": entity}


def test_healing_zero_health_clears_defeat_but_cannot_resurrect(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = defeat(app)
    admin, player, card, path, run, target, base = game
    client, rescue = healer(app, game)
    response = command(
        client,
        base,
        rescue,
        "tabletop.magic.invoke",
        {"spell_id": "MEND", "target_id": target},
        "rescue",
    )
    assert response.status_code == 200, response.get_json()
    body = state.projections["tabletop.entities"][target]
    assert body["hp"] == 4 and body["defeated"] is False
    assert target not in state.projections[VITALS]
    assert state.projections["tabletop.entities"][rescue["entity_id"]]["mana"] == 6
    body.update(hp=0, dead=True, defeated=True)
    advance_clock(admin, base, 6)
    before = state.state_hash, state.version
    assert (
        command(
            client,
            base,
            rescue,
            "tabletop.magic.invoke",
            {"spell_id": "MEND", "target_id": target},
            "no-resurrection",
        ).status_code
        == 400
    )
    assert (state.state_hash, state.version) == before and body["dead"]


def test_stabilization_is_contact_limited_and_costs_time_once(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = defeat(app)
    admin, player, card, path, run, target, base = game
    client, rescue = healer(app, game)
    first = command(client, base, rescue, "tabletop.combat.stabilize", {"target_id": target}, "aid")
    assert first.status_code == 200, first.get_json()
    assert state.projections[VITALS][target]["status"] == "STABLE"
    assert state.projections["tabletop.action_time"][rescue["entity_id"]]["ready_seconds"] == 6
    before = state.state_hash, state.version
    assert (
        command(
            client, base, rescue, "tabletop.combat.stabilize", {"target_id": target}, "aid"
        ).get_json()
        == first.get_json()
    )
    assert (state.state_hash, state.version) == before
    advance_clock(admin, base, 6)
    before = state.state_hash, state.version
    assert (
        command(
            client,
            base,
            rescue,
            "tabletop.combat.stabilize",
            {"target_id": target},
            "already-stable",
        ).status_code
        == 400
    )
    assert (state.state_hash, state.version) == before


def test_distant_or_forged_first_aid_leaves_no_writes(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, state, receipt = defeat(app)
    admin, player, card, path, run, target, base = game
    client, rescue = healer(app, game)
    moved = command(client, base, rescue, "tabletop.spatial.move", {"dx": 0, "dy": 1}, "away")
    assert moved.status_code == 200, moved.get_json()
    advance_clock(admin, base, 1)
    before = state.state_hash, state.version
    assert (
        command(
            client, base, rescue, "tabletop.combat.stabilize", {"target_id": target}, "distant"
        ).status_code
        == 400
    )
    assert (
        command(
            client,
            base,
            rescue,
            "tabletop.combat.stabilize",
            {"target_id": target, "successes": 3},
            "forged",
        ).status_code
        == 400
    )
    assert (state.state_hash, state.version) == before


@pytest.mark.parametrize("physical", [{"dead": True}, {"hp": 0}, {"conditions": ["unconscious"]}])
def test_unaware_body_has_no_new_sight_or_sound_grants(monkeypatch, tmp_path, physical):
    from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver

    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    simulation = app.extensions["simulation"]
    state = simulation.states.get(uuid.UUID(base["branch_id"]))
    state.projections["tabletop.entities"][target].update(physical)
    assert GridSpatialPerceptionResolver().visible_entities(state, uuid.UUID(target)) == {
        uuid.UUID(target): 1.0
    }
    response = command(
        player,
        base,
        card,
        "tabletop.dialogue.speak",
        {"text": "This must not reach a dead mind."},
        "after-death",
    )
    assert response.status_code == 200, response.get_json()
    event = uuid.UUID(response.get_json()["event"]["event_id"])
    assert simulation.perception_grant(event, uuid.UUID(target)) is None

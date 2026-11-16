from __future__ import annotations

import uuid

import pytest

from domains.tabletop.world_time import advance_result, read_clock
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_npc_goals import configure_subjective
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.population.test_life import configure_game_life

pytestmark = pytest.mark.unit


def condition(admin, base, target, duration=5, kind="stunned", key="stun"):
    return api_command(
        admin,
        base,
        "tabletop.condition.apply",
        {
            "target_id": target,
            "condition": kind,
            "duration_seconds": duration,
        },
        key,
    )


def physical_projection(state):
    return {key: value for key, value in state.projections.items() if key != "tabletop.clock"}


def projected_advance(state, until):
    for delta in advance_result(state, read_clock(state), until).deltas:
        state.apply(delta)


@pytest.mark.parametrize("weather,expected", [(False, 5), (True, 3)])
def test_midstep_expiry_and_weather_are_partition_invariant(
    monkeypatch, tmp_path, weather, expected
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    condition(admin, base, target)
    if weather:
        for when, raining in [(2, True), (7, False)]:
            api_command(
                admin,
                base,
                "tabletop.weather.schedule",
                {
                    "due_seconds": when,
                    "zone_id": "world",
                    "raining": raining,
                },
                f"rain-{when}",
            )
    original = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    whole, split = original.working_copy(), original.working_copy()
    projected_advance(whole, 10)
    for end in [2, 5, 7, 10]:
        projected_advance(split, end)
    assert physical_projection(whole) == physical_projection(split)
    assert whole.projections["tabletop.entities"][target]["weeded_units"] == expected
    assert whole.projections["tabletop.entities"][target]["timed_conditions"] == {}
    assert "weeded_units" not in original.projections["tabletop.entities"][target]
    advance_clock(admin, base, 10)
    assert physical_projection(original) == physical_projection(whole)


def test_busy_body_cannot_work_during_its_reserved_action(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    assert (
        command(
            admin, base, {"entity_id": target}, "tabletop.combat.guard", {}, "guard-worker"
        ).status_code
        == 200
    )
    advance_clock(admin, base, 10)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.entities"][target]["weeded_units"] == 4
    assert not state.projections["tabletop.entities"][target]["guarded"]
    assert state.projections["tabletop.activities"][target]["progress_seconds"] == 4


def test_conditions_stack_expire_and_preserve_permanent_sources(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    first = condition(admin, base, card["entity_id"], duration=5)
    condition(admin, base, card["entity_id"], duration=8, key="another-stun")
    original = state.state_hash, state.version
    assert condition(admin, base, card["entity_id"], duration=5) == first
    assert (state.state_hash, state.version) == original
    live = player.get(f"/api/v2/player/characters/{card['character_id']}/live-state").get_json()
    assert live["body"]["status"] == "INCAPACITATED" and live["body"]["conditions"] == ["stunned"]
    assert "source_command_id" not in str(live)
    advance_clock(admin, base, 5)
    assert (
        command(player, base, card, "tabletop.combat.guard", {}, "still-stunned").status_code == 400
    )
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert len(body["timed_conditions"]) == 1
    body["conditions"] = ["STUNNED"]
    advance_clock(admin, base, 8)
    body = state.projections["tabletop.entities"][card["entity_id"]]
    assert body["timed_conditions"] == {} and body["conditions"] == ["STUNNED"]
    assert command(player, base, card, "tabletop.combat.guard", {}, "permanent").status_code == 400
    body["conditions"] = []
    assert command(player, base, card, "tabletop.combat.guard", {}, "recovered").status_code == 200


def test_planned_npc_only_works_after_stun_ends(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, *_ = configure_subjective(app)
    admin, player, card, path, run, target, base = game
    condition(admin, base, target)
    advance_clock(admin, base, 10)
    body = (
        app.extensions["simulation"]
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][target]
    )
    assert body["weeded_units"] == 5


def test_condition_requires_world_authority_and_rejects_client_expiry(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    other = admin.post("/api/v2/worlds", json={"name": "Other authority"}).get_json()
    assert (
        admin.put(
            f"/api/v2/admin/users/{card['owner_user_id']}/worlds/{other['world_id']}/roles",
            json={"roles": ["DM"]},
        ).status_code
        == 200
    )
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version
    request = {
        **base,
        "command_type": "tabletop.condition.apply",
        "idempotency_key": "denied",
        "parameters": {"target_id": target, "condition": "stunned", "duration_seconds": 5},
    }
    assert player.post("/api/v2/commands", json=request).status_code == 403
    assert (state.state_hash, state.version) == before
    for update in [
        {"expires_seconds": 0},
        {"duration_seconds": 0},
        {"duration_seconds": 86401},
        {"condition": "DEAD"},
        {"target_id": str(uuid.uuid4())},
    ]:
        request["parameters"] = {
            "target_id": target,
            "condition": "stunned",
            "duration_seconds": 5,
            **update,
        }
        assert admin.post("/api/v2/commands", json=request).status_code == 400
        assert (state.state_hash, state.version) == before


def test_blessings_have_independent_clock_expiries_and_retry_once(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    first = api_command(
        admin,
        base,
        "tabletop.divine.bless",
        {"target_id": target, "blessing": "Hope", "duration_turns": 1},
        "hope",
    )
    assert (
        api_command(
            admin,
            base,
            "tabletop.divine.bless",
            {"target_id": target, "blessing": "Hope", "duration_turns": 1},
            "hope",
        )
        == first
    )
    api_command(
        admin,
        base,
        "tabletop.divine.bless",
        {"target_id": target, "blessing": "Hope", "duration_turns": 2},
        "more-hope",
    )
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    advance_clock(admin, base, 6)
    remaining = state.projections["tabletop.entities"][target]["blessings"]
    assert remaining == [{"name": "Hope", "remaining_turns": 1, "expires_seconds": 12}]
    advance_clock(admin, base, 12)
    assert state.projections["tabletop.entities"][target]["blessings"] == []


def test_legacy_blessing_remaining_turns_anchor_on_first_new_clock_advance(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    state.projections["tabletop.entities"][target]["blessings"] = [
        {"name": "Legacy", "remaining_turns": 2}
    ]
    advance_clock(admin, base, 6)
    assert state.projections["tabletop.entities"][target]["blessings"] == [
        {"name": "Legacy", "remaining_turns": 1, "expires_seconds": 12}
    ]
    advance_clock(admin, base, 12)
    assert state.projections["tabletop.entities"][target]["blessings"] == []


@pytest.mark.parametrize("life", [False, True])
def test_routine_suspension_and_recovery_are_partition_invariant(monkeypatch, tmp_path, life):
    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, card, path, run, target, base = game
    if life:
        configure_game_life(app, game)
    else:
        seed_routine(app, admin, base, target)
    condition(admin, base, target)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    whole, split = state.working_copy(), state.working_copy()
    projected_advance(whole, 10)
    for until in (5, 10):
        projected_advance(split, until)
    assert physical_projection(whole) == physical_projection(split)
    assert whole.projections["tabletop.entities"][target]["weeded_units"] == 5
    assert whole.projections["tabletop.entities"][target]["hunger"] == 10


@pytest.mark.parametrize("busy,blocked", [(False, 5), (True, 6)])
def test_social_attendance_waits_for_both_capability_and_action_readiness(
    monkeypatch, tmp_path, busy, blocked
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    if busy:
        assert (
            command(
                admin, base, {"entity_id": target}, "tabletop.combat.guard", {}, "guard"
            ).status_code
            == 200
        )
    else:
        condition(admin, base, target)
    response = api_command(
        admin,
        base,
        "tabletop.obligation.schedule",
        {
            "participants": [target, card["entity_id"]],
            "place": {"x": 0, "y": 0},
            "radius": 2,
            "starts_seconds": 0,
            "duration_seconds": 10,
            "grace_seconds": 30,
            "lead_seconds": 0,
        },
        "meeting",
    )
    advance_clock(admin, base, 10)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    meeting = state.projections["tabletop.obligations"][
        response["result"]["result"]["obligation_id"]
    ]
    assert meeting["progress_seconds"] == 10 - blocked and meeting["status"] == "ATTENDING"
    for entity in (target, card["entity_id"]):
        assert state.projections["tabletop.entities"][entity]["social_seconds"] == 10 - blocked


def test_bounded_stacks_preserve_original_retry_at_capacity(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    first = condition(admin, base, target, key="stack-0")
    for index in range(1, 32):
        condition(admin, base, target, key=f"stack-{index}")
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.condition.apply",
            "idempotency_key": "overflow",
            "parameters": {"target_id": target, "condition": "stunned", "duration_seconds": 5},
        },
    )
    assert response.status_code == 400 and (state.state_hash, state.version) == before
    assert condition(admin, base, target, key="stack-0") == first
    assert (state.state_hash, state.version) == before


@pytest.mark.parametrize("mode", ["manual", "routine", "life", "planned"])
def test_missing_health_never_fabricates_offscreen_work(monkeypatch, tmp_path, mode):
    app = _app(monkeypatch, tmp_path)
    if mode == "planned":
        game, *_ = configure_subjective(app)
    else:
        game = clock_game(app)
    admin, player, card, path, run, target, base = game
    if mode == "routine":
        seed_routine(app, admin, base, target)
    elif mode == "life":
        configure_game_life(app, game)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    state.projections["tabletop.entities"][target].pop("hp")
    advance_clock(admin, base, 10)
    body = state.projections["tabletop.entities"][target]
    activity = state.projections["tabletop.activities"][target]
    assert body.get("weeded_units", 0) == 0
    assert activity["progress_seconds"] == 0
    assert activity["status"] == "WAITING" and activity["reason"] == "INCAPACITATED"

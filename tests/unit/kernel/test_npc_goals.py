from __future__ import annotations

import uuid

import pytest

from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_population_runtime_api import seed_routine
from tests.unit.kernel.test_world_time import api_command, clock_game

pytestmark = pytest.mark.unit


def runtime_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/population"


def clock_path(base):
    return f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"


def configure_subjective(app, game=None, *, curious=False):
    game = game or clock_game(app)
    admin, player, player_card, player_path, run, target, base = game
    card_response = admin.post(
        "/api/v2/player/characters",
        json={
            "world_id": base["world_id"],
            "name": "Mara Gardener",
            "authored_identity": {
                "backstory": "A villager who tends the shared garden.",
                "motives": ["Care for neighbors"],
                "secrets": ["PRIVATE_NPC_VOW"],
            },
        },
    )
    assert card_response.status_code == 201, card_response.get_json()
    card = card_response.get_json()
    path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/entities/{target}"
    association = (
        f"/api/v2/dm/worlds/{base['world_id']}/branches/{base['branch_id']}"
        f"/entities/{target}/character-card"
    )
    linked = admin.put(association, json={"character_id": card["character_id"]})
    assert linked.status_code == 200, linked.get_json()
    assert (
        admin.put(association, json={"character_id": card["character_id"]}).get_json()
        == linked.get_json()
    )
    history = admin.get(f"/api/v2/player/characters/{card['character_id']}/history").get_json()[
        "items"
    ]
    persona = admin.post(
        "/api/v2/personas/generate",
        json={
            "purpose": "CHARACTER",
            "seed": 32,
            "fixed": {
                "agreeableness": "LOW" if curious else "HIGH",
                "community_loyalty": "LOW" if curious else "HIGH",
                "curiosity": "HIGH" if curious else "LOW",
                "openness": "HIGH" if curious else "LOW",
                "risk_tolerance": "LOW",
            },
        },
    )
    assert persona.status_code == 201, persona.get_json()
    compiled = admin.post(f"/api/v2/personas/{persona.get_json()['persona_id']}/compile").get_json()
    pinned = admin.post(
        path + "/character-binding",
        json={
            "character_id": card["character_id"],
            "run_id": run,
            "card_revision_id": history[-1]["revision_id"],
            "persona_version_id": compiled["persona_version"],
        },
    )
    assert pinned.status_code == 200, pinned.get_json()
    seed_routine(app, admin, base, target)
    config = {
        "entity_id": target,
        "expected_version": 1,
        "hunger_limit": 10000,
        "fatigue_limit": 10000,
        "life": {
            "home": {"x": 1, "y": 0},
            "workplace": {"x": 1, "y": 0},
            "step_seconds": 10,
            "sleep_start_seconds": 10000,
            "sleep_seconds": 60,
            "planning": {
                "motivated": True,
                "retry_seconds": 30,
                "goals": [
                    {
                        "goal_id": "neighbors",
                        "kind": "WEED",
                        "motive": "CARE",
                        "place": {"x": 1, "y": 0},
                        "seconds_per_day": 120,
                        "priority": 50,
                    },
                    {
                        "goal_id": "explore",
                        "kind": "REST",
                        "motive": "CURIOSITY",
                        "place": {"x": 1, "y": 0},
                        "seconds_per_day": 120,
                        "priority": 50,
                    },
                ],
            },
        },
    }
    api_command(admin, base, "tabletop.routine.configure", config, "motivated")
    return game, card, path, association, config


def advance_game(admin, base, until, key=None):
    clock = admin.get(clock_path(base)).get_json()["clock"]
    return api_command(
        admin,
        base,
        "tabletop.clock.advance",
        {
            "expected_epoch": clock["epoch"],
            "expected_seconds": clock["seconds"],
            "to_seconds": until,
        },
        key or f"advance:{until}",
    )


def say(
    player, base, card, predicate, value, *, subject_type="entity", subject_id=None, key="belief"
):
    response = player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": "tabletop.dialogue.speak",
            "idempotency_key": key,
            "parameters": {
                "text": "An in-world statement.",
                "claims": [
                    {
                        "subject_type": subject_type,
                        "subject_id": subject_id,
                        "predicate": predicate,
                        "value": value,
                        "confidence": 1.0,
                    }
                ],
            },
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_persona_changes_actual_offscreen_goal_and_canonical_work(monkeypatch, tmp_path):
    for curious in (False, True):
        app = _app(monkeypatch, tmp_path)
        game, card, path, association, config = configure_subjective(app, curious=curious)
        admin, player, player_card, player_path, run, target, base = game
        advance_game(admin, base, 20)
        row = admin.get(runtime_path(base)).get_json()["routines"][target]
        assert row["planner"]["selected"] == ("explore" if curious else "neighbors")
        activity = admin.get(clock_path(base)).get_json()["activities"][target]
        assert activity["kind"] == ("REST" if curious else "WEED")
        assert activity["progress_seconds"] == 20
        assert (
            app.extensions["simulation"].replay(uuid.UUID(base["branch_id"])).state_hash
            == app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"])).state_hash
        )


def test_observed_belief_preempts_persona_goal_and_preserves_partial_work(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    advance_game(admin, base, 20)
    said = say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 100},
        subject_id=target,
    )
    advance_game(admin, base, 40)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["planner"]["selected"] == "explore"
    assert row["planner"]["spent"] == {"neighbors": 20, "explore": 20}
    assert said["event"]["event_id"] in row["motivation"]["source_event_ids"]
    assert player.get(runtime_path(base)).status_code == 403
    for private in ("motivation", "input_hash", "PRIVATE_NPC_VOW", "belief_ids", "persona_version"):
        assert private not in str(player.get(player_path + "/scene").get_json())


def test_npc_card_association_rejects_player_and_foreign_or_occupied_body(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    assert (
        player.put(association, json={"character_id": player_card["character_id"]}).status_code
        == 403
    )
    assert (
        admin.put(association, json={"character_id": player_card["character_id"]}).status_code
        == 400
    )
    world = admin.post("/api/v2/worlds", json={"name": "Other"}).get_json()
    foreign_path = association.replace(str(base["world_id"]), world["world_id"])
    assert admin.put(foreign_path, json={"character_id": card["character_id"]}).status_code == 400


def test_danger_belief_and_contradiction_change_goals_without_changing_world_truth(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    advance_game(admin, base, 20)
    value = {"place": {"x": 1, "y": 0}, "dangerous": True}
    say(player, base, player_card, "place_danger", value, subject_type="place", key="danger")
    advance_game(admin, base, 40)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert set(row["motivation"]["avoided"]) == {"neighbors", "explore"}
    assert row["planner"]["reason"] == "BELIEVED_DANGER"
    assert admin.get(clock_path(base)).get_json()["activities"][target]["kind"] == "REST"
    say(
        player,
        base,
        player_card,
        "place_danger",
        {**value, "dangerous": False},
        subject_type="place",
        key="safe",
    )
    advance_game(admin, base, 60)
    current = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert not current["motivation"]["avoided"]
    assert current["planner"]["spent"]["neighbors"] == 40
    body = (
        app.extensions["simulation"]
        .states.get(uuid.UUID(base["branch_id"]))
        .projections["tabletop.entities"][target]
    )
    assert body["hp"] == 100 and "place_danger" not in body


def test_forged_unsourced_mind_and_private_world_notes_cannot_change_motivation(
    monkeypatch, tmp_path
):
    from cognition.models import Belief

    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    before = admin.get(runtime_path(base)).get_json()["routines"][target]["motivation"]
    branch, body = uuid.UUID(base["branch_id"]), uuid.UUID(target)
    store = app.extensions["minds"]
    mind = store.get(body, branch_id=branch)
    forged = Belief(
        entity_id=body,
        subject_type="entity",
        subject_id=body,
        predicate="motive_importance",
        value={"motive": "CURIOSITY", "importance": 100},
        confidence=1,
    )
    store.restore(mind.model_copy(update={"beliefs": (forged,)}), branch_id=branch)
    app.extensions["simulation"].entities[(branch, body)].secret_state["dm_note"] = (
        "The garden is cursed."
    )
    advance_game(admin, base, 20)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["motivation"] == before
    assert row["planner"]["selected"] == "neighbors"


def test_unbound_motivated_configuration_fails_without_partial_writes(monkeypatch, tmp_path):
    from tests.unit.population.test_planning import configure_game_plan

    app = _app(monkeypatch, tmp_path)
    game = clock_game(app)
    admin, player, player_card, player_path, run, target, base = game
    config = configure_game_plan(app, game)
    before = admin.get(runtime_path(base)).get_json()
    config["expected_version"] = 3
    config["life"]["planning"]["motivated"] = True
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.routine.configure",
            "idempotency_key": "unbound",
            "parameters": config,
        },
    )
    assert response.status_code == 400
    assert admin.get(runtime_path(base)).get_json() == before


def test_world_runner_requires_explicit_mind_read_grant_and_advances_when_granted(
    monkeypatch, tmp_path
):
    from datetime import timedelta

    from tests.unit.kernel.test_world_time import NOW

    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    old = admin.get(clock_path(base)).get_json()["clock"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": old["epoch"],
            "executor_actor_id": old["executor_actor_id"],
            "paused": False,
            "seconds_per_tick": 10,
            "wall_time": NOW.isoformat(),
        },
        "unreadable-executor",
    )
    before = admin.get(clock_path(base)).get_json()
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=2)) == 0
    assert admin.get(clock_path(base)).get_json() == before
    agent = admin.post(
        "/api/v2/actors",
        json={
            "world_id": base["world_id"],
            "display_name": "NPC life executor",
            "kind": "AGENT",
            "capabilities": ["world.read", "action.propose", "action.commit", "mind.read.all"],
        },
    ).get_json()["actor_id"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 2,
            "executor_actor_id": agent,
            "paused": False,
            "seconds_per_tick": 10,
            "wall_time": NOW.isoformat(),
        },
        "readable-executor",
    )
    assert app.extensions["world_runner"].run_once(NOW + timedelta(seconds=2)) == 1
    assert admin.get(clock_path(base)).get_json()["clock"]["seconds"] == 10


def test_motivated_partitions_freeze_identical_inputs_and_physical_progress(monkeypatch, tmp_path):
    from kernel.contracts import CommandProposal

    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    sim = app.extensions["simulation"]
    initial = sim.states.get(uuid.UUID(base["branch_id"])).working_copy()
    handler = sim.bus.definition("tabletop.clock.advance").handler
    outputs = []
    for boundaries in ([200], [1, 7, 30, 99, 120, 137, 170, 200]):
        state = initial.working_copy()
        for end in boundaries:
            result = handler(
                CommandProposal(
                    **base,
                    actor_id=app.extensions["demo_ids"]["actor_id"],
                    command_type="tabletop.clock.advance",
                    parameters={
                        "expected_epoch": 1,
                        "expected_seconds": state.projections["tabletop.clock"]["singleton"][
                            "seconds"
                        ],
                        "to_seconds": end,
                    },
                    idempotency_key=str(end),
                ),
                state,
            )
            for delta in result.deltas:
                state.apply(delta)
        outputs.append(
            {key: value for key, value in state.projections.items() if key != "tabletop.clock"}
        )
    assert outputs[0] == outputs[1]


def test_unheard_claims_do_not_change_the_npcs_intentions(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    original = admin.get(runtime_path(base)).get_json()["routines"][target]["motivation"]
    for step in range(11):
        response = player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": player_card["entity_id"],
                "command_type": "tabletop.spatial.move",
                "idempotency_key": f"leave:{step}",
                "parameters": {"dx": 1, "dy": 0},
            },
        )
        assert response.status_code == 200, response.get_json()
    say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 100},
        subject_id=target,
    )
    advance_game(admin, base, 20)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["motivation"] == original and row["planner"]["selected"] == "neighbors"


def test_trial_cannot_reuse_a_canonical_persona_binding_or_change_either_branch(
    monkeypatch, tmp_path
):
    from kernel.contracts import CommandProposal

    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    source = app.extensions["simulation"]
    canonical = source.states.get(uuid.UUID(base["branch_id"]))
    snapshot = source.create_branch_snapshot(canonical.branch_id)
    trial, trial_run = source.create_trial(canonical.world_id, snapshot.snapshot_id, 44)
    canonical_hash = canonical.state_hash
    trial_hash = source.states.get(trial.branch_id).state_hash
    with pytest.raises(ValueError, match="pinned CHARACTER binding"):
        source.submit(
            CommandProposal(
                world_id=canonical.world_id,
                branch_id=trial.branch_id,
                run_id=trial_run.run_id,
                actor_id=app.extensions["demo_ids"]["actor_id"],
                command_type="tabletop.clock.advance",
                idempotency_key="trial-must-not-borrow-pin",
                parameters={"expected_epoch": 1, "expected_seconds": 0, "to_seconds": 20},
            )
        )
    assert source.states.get(canonical.branch_id).state_hash == canonical_hash
    assert source.states.get(trial.branch_id).state_hash == trial_hash


@pytest.mark.parametrize(
    "value",
    [
        {"motive": [], "importance": 100},
        {"motive": "CURIOSITY", "importance": True},
        {"motive": "UNKNOWN", "importance": 100},
    ],
)
def test_malformed_heard_claims_cannot_crash_or_redirect_world_planning(
    monkeypatch, tmp_path, value
):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    admin, player, player_card, player_path, run, target, base = game
    before = admin.get(runtime_path(base)).get_json()["routines"][target]["motivation"]
    say(player, base, player_card, "motive_importance", value, subject_id=target)
    advance_game(admin, base, 20)
    assert admin.get(runtime_path(base)).get_json()["routines"][target]["motivation"] == before


def check_npc_card_source_authority(game, source):
    admin, dm, player_card, player_path, run, target, base = game
    account = dm.get("/api/v2/auth/session").get_json()["user"]
    roles = admin.put(
        f"/api/v2/admin/users/{account['user_id']}/worlds/{base['world_id']}/roles",
        json={"roles": ["DM", "PLAYER"]},
    )
    assert roles.status_code == 200, roles.get_json()
    owner = dm if source == "OWN_UNASSIGNED" else admin
    payload = {"name": "Private source", "authored_identity": {"secrets": ["SOURCE_CARD_SECRET"]}}
    if source == "WORLD_ASSIGNED":
        payload["world_id"] = base["world_id"]
    created = owner.post("/api/v2/player/characters", json=payload)
    assert created.status_code == 201, created.get_json()
    card = created.get_json()
    route = (
        f"/api/v2/dm/worlds/{base['world_id']}/branches/{base['branch_id']}"
        f"/entities/{target}/character-card"
    )
    response = dm.put(route, json={"character_id": card["character_id"]})
    if source == "OTHER_UNASSIGNED":
        assert response.status_code == 403, response.get_json()
        assert "SOURCE_CARD_SECRET" not in response.get_data(as_text=True)
        assert dm.put(route, json={"character_id": card["character_id"]}).status_code == 403
        saved = next(
            row
            for row in owner.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == card["character_id"]
        )
        assert saved["world_id"] is None and saved["entity_id"] is None
        response = admin.put(route, json={"character_id": card["character_id"]})
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["character"]["authored_identity"]["secrets"] == [
        "SOURCE_CARD_SECRET"
    ]
    assert owner.get("/api/v2/player/characters").status_code == 200
    authorized = admin if source == "OTHER_UNASSIGNED" else dm
    assert (
        authorized.put(route, json={"character_id": card["character_id"]}).get_json()
        == response.get_json()
    )


@pytest.mark.parametrize("source", ["OTHER_UNASSIGNED", "OWN_UNASSIGNED", "WORLD_ASSIGNED"])
def test_npc_card_association_requires_source_card_authority(monkeypatch, tmp_path, source):
    app = _app(monkeypatch, tmp_path)
    check_npc_card_source_authority(clock_game(app), source)


def check_active_motivation_survives_recent_window(game, path):
    admin, player, player_card, player_path, run, target, base = game
    say(
        player,
        base,
        player_card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 100},
        subject_id=target,
        key="lasting-importance",
    )
    say(
        player,
        base,
        player_card,
        "place_danger",
        {"place": {"x": 1, "y": 0}, "dangerous": True},
        subject_type="place",
        key="lasting-danger",
    )
    advance_game(admin, base, 20)
    before = admin.get(runtime_path(base)).get_json()["routines"][target]["motivation"]
    for index in range(81):
        say(
            player,
            base,
            player_card,
            "market_news",
            {"edition": index},
            subject_id=player_card["entity_id"],
            key=f"unrelated:{index}",
        )
    context = admin.get(path + "/context?run_id=" + run)
    assert context.status_code == 200, context.get_json()
    assert len(context.get_json()["situation"]["experiences"]) == 80
    advance_game(admin, base, 40)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert row["motivation"] == before
    assert row["planner"]["reason"] == "BELIEVED_DANGER"
    say(
        player,
        base,
        player_card,
        "place_danger",
        {"place": {"x": 1, "y": 0}, "dangerous": False},
        subject_type="place",
        key="danger-corrected",
    )
    advance_game(admin, base, 60)
    row = admin.get(runtime_path(base)).get_json()["routines"][target]
    assert not row["motivation"]["avoided"]
    assert row["planner"]["selected"] == "explore"
    assert row["planner"]["spent"] == {"explore": 20}


def test_active_danger_and_importance_beliefs_survive_eighty_newer_events(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    game, card, path, association, config = configure_subjective(app)
    check_active_motivation_survives_recent_window(game, path)

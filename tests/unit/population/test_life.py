from __future__ import annotations

import uuid

import pytest

from domains.tabletop.activities import ACTIVITIES
from population.life import OBLIGATIONS
from population.routines import ROUTINES
from population.runtime import HISTORY, MEMBERS
from tests.unit.kernel.test_world_time import advance, send
from tests.unit.population.test_runtime import runtime, state

pytestmark = pytest.mark.unit


def configure_game_life(app, game):
    from tests.unit.kernel.test_population_runtime_api import seed_routine
    from tests.unit.kernel.test_world_time import api_command

    admin, player, card, path, run, target, base = game
    root, member_path, bind_body = seed_routine(app, admin, base, target)
    api_command(
        admin,
        base,
        "tabletop.routine.configure",
        {
            "entity_id": target,
            "expected_version": 1,
            "work_seconds": 120,
            "rest_seconds": 60,
            "hunger_limit": 10000,
            "fatigue_limit": 10000,
            "life": {
                "home": {"x": 3, "y": 0},
                "workplace": {"x": 1, "y": 0},
                "step_seconds": 10,
                "sleep_start_seconds": 60,
                "sleep_seconds": 60,
            },
        },
        "life",
    )
    return root, member_path


def game_meeting(admin, base, target, *, starts=200, repeat=None):
    from tests.unit.kernel.test_world_time import api_command

    partner = str(uuid.uuid4())
    api_command(
        admin,
        base,
        "tabletop.entity.spawn",
        {
            "entity_id": partner,
            "name": "Friend",
            "entity_type": "any_person",
            "public_state": {"hp": 100, "x": 3},
        },
        "friend",
    )
    result = api_command(
        admin,
        base,
        "tabletop.obligation.schedule",
        {
            "participants": [target, partner],
            "place": {"x": 3, "y": 0},
            "starts_seconds": starts,
            "duration_seconds": 20,
            "grace_seconds": 30,
            "lead_seconds": 50,
            "repeat_seconds": repeat,
        },
        "social",
    )
    return partner, result["result"]["result"]["obligation_id"]


def living(*, sleep_start=60, **changes):
    app, ids, body, persona, source, bound = runtime()
    params = {
        "entity_id": body,
        "expected_version": 1,
        "work_seconds": 120,
        "rest_seconds": 60,
        "fatigue_limit": 10000,
        "hunger_limit": 10000,
        "life": {
            "home": {"x": 52, "y": 0},
            "workplace": {"x": 50, "y": 0},
            "step_seconds": 10,
            "sleep_start_seconds": sleep_start,
            "sleep_seconds": 60,
        },
        **changes,
    }
    send(app, ids, "tabletop.routine.configure", params, "life")
    return app, ids, body


def outcomes(current):
    return {
        key: current.projections.get(key, {})
        for key in (
            MEMBERS,
            HISTORY,
            ROUTINES,
            ACTIVITIES,
            OBLIGATIONS,
            "tabletop.entities",
            "tabletop.spatial.positions",
        )
    }


def meeting(app, ids, body, *, starts=100, duration=20, grace=30, repeat=None, **changes):
    partner = uuid.uuid5(uuid.UUID(body), "social-partner")
    if str(partner) not in state(app, ids).projections["tabletop.entities"]:
        send(
            app,
            ids,
            "tabletop.entity.spawn",
            {
                "entity_id": str(partner),
                "name": "Friend",
                "entity_type": "any_person",
                "public_state": {"hp": 100, "x": 52},
            },
            "partner",
        )
    receipt = send(
        app,
        ids,
        "tabletop.obligation.schedule",
        {
            "participants": [body, str(partner)],
            "place": {"x": 52, "y": 0},
            "starts_seconds": starts,
            "duration_seconds": duration,
            "grace_seconds": grace,
            "lead_seconds": 50,
            "repeat_seconds": repeat,
            **changes,
        },
        "meeting:" + str(starts),
    )
    return str(partner), receipt.result.result["obligation_id"]


def test_commute_daily_sleep_and_resumed_work_are_partition_invariant():
    results = []
    for boundaries in ([160], [30, 60, 70, 75, 80, 100, 120, 130, 140, 160]):
        app, ids, body = living()
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        physical = current.projections["tabletop.entities"][body]
        assert physical["sleep_seconds"] == 40
        assert physical["travel_steps"] == 4
        assert physical["weeded_units"] == 80
        assert not physical["asleep"]
        assert current.projections["tabletop.spatial.positions"][body]["x"] == 50
        assert current.projections[ACTIVITIES][body]["progress_seconds"] == 80
        assert app.replay(ids["branch_id"]).state_hash == current.state_hash
        results.append(outcomes(current))
    assert results[0] == results[1]


@pytest.mark.parametrize("life", [False, True])
def test_meal_completion_records_actual_input_before_replacing_phase(life):
    if life:
        app, ids, body = living(sleep_start=1000, hunger_limit=60)
    else:
        app, ids, body, _, _, _ = runtime()
        send(
            app,
            ids,
            "tabletop.routine.configure",
            {"entity_id": body, "expected_version": 1, "work_seconds": 120, "hunger_limit": 60},
            "meal-routine",
        )
    advance(app, ids, 1)
    work_id = state(app, ids).projections[ACTIVITIES][body]["activity_id"]
    advance(app, ids, 62)
    meal = state(app, ids).projections[ACTIVITIES][body]
    assert meal["kind"] == "EAT" and meal["due_seconds"] == 65
    assert meal["progress_seconds"] == 2 and meal["inputs"]["food"] == 0
    assert state(app, ids).projections["tabletop.entities"][body]["inventory"]["food"] == 3

    receipt = advance(app, ids, 70)
    records = receipt.event.payload["activity_records"]
    finished = next(row for row in records if row["activity_id"] == meal["activity_id"])
    assert finished["due_seconds"] == 65 and finished["status"] == "COMPLETED"
    assert finished["inputs"]["food"] == 1 and finished["outputs"]["meals_eaten"] == 1
    assert finished["outputs"]["hunger_relieved"] == 65
    assert {"details", "origin", "task_key", "routine_id"}.isdisjoint(finished)
    current = state(app, ids)
    assert current.projections["tabletop.entities"][body]["inventory"]["food"] == 2
    work = current.projections[ACTIVITIES][body]
    assert work["activity_id"] == work_id and work["due_seconds"] == 125
    assert work["outputs"]["weeded_units"] == 65
    assert app.replay(ids["branch_id"]).state_hash == current.state_hash


def test_route_uses_manual_step_collisions_and_reroutes_without_teleporting():
    app, ids, body = living()
    current = state(app, ids)
    current.projections.setdefault("tabletop.obstacles", {})[str(uuid.uuid4())] = {"x": 51, "y": 0}
    advance(app, ids, 70)
    actual = state(app, ids).projections["tabletop.spatial.positions"][body]
    assert abs(actual["x"] - 50) + abs(actual["y"]) == 1
    assert (actual["x"], actual["y"]) != (51, 0)
    advance(app, ids, 100)
    assert state(app, ids).projections["tabletop.entities"][body]["travel_steps"] == 4
    assert state(app, ids).projections["tabletop.entities"][body]["asleep"]


def test_joint_social_attendance_and_return_to_work_are_partition_invariant():
    results = []
    for boundaries in ([150], [40, 50, 60, 70, 99, 100, 110, 120, 130, 140, 150]):
        app, ids, body = living(sleep_start=1000)
        partner, identity = meeting(app, ids, body)
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        obligation = current.projections[OBLIGATIONS][identity]
        assert obligation["status"] == "COMPLETED" and obligation["completed_count"] == 1
        assert obligation["last_outcome"]["at_seconds"] == 120
        for key in (body, partner):
            assert current.projections["tabletop.entities"][key]["social_seconds"] == 20
        assert current.projections["tabletop.entities"][body]["weeded_units"] == 60
        results.append(outcomes(current))
    assert results[0] == results[1]


def test_unavailable_partner_causes_missed_obligation_not_invented_attendance():
    app, ids, body = living(sleep_start=1000)
    partner, identity = meeting(app, ids, body)
    state(app, ids).projections["tabletop.entities"][partner]["hp"] = 0
    advance(app, ids, 160)
    obligation = state(app, ids).projections[OBLIGATIONS][identity]
    assert obligation["status"] == "MISSED" and obligation["missed_count"] == 1
    assert obligation["progress_seconds"] == 0
    assert state(app, ids).projections["tabletop.entities"][body].get("social_seconds", 0) == 0


def test_recurring_obligation_survives_multiple_days_without_duplicate_rewards():
    results = []
    for boundaries in ([750], [70, 120, 140, 650, 670, 700, 720, 750]):
        app, ids, body = living(sleep_start=1000)
        partner, identity = meeting(app, ids, body, repeat=600)
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        obligation = current.projections[OBLIGATIONS][identity]
        assert obligation["completed_count"] == 2 and obligation["occurrence"] == 1
        assert current.projections["tabletop.entities"][body]["social_seconds"] == 40
        results.append(outcomes(current))
    assert results[0] == results[1]


def test_injury_wakes_sleep_and_resumes_after_quiet_window():
    app, ids, body = living()
    advance(app, ids, 90)
    assert state(app, ids).projections["tabletop.entities"][body]["asleep"]
    state(app, ids).projections["tabletop.entities"][body]["hp"] = 90
    advance(app, ids, 100)
    assert not state(app, ids).projections["tabletop.entities"][body]["asleep"]
    assert state(app, ids).projections[ACTIVITIES][body]["reason"] == "DANGER"
    assert state(app, ids).projections["tabletop.entities"][body]["sleep_seconds"] == 10


def test_blocked_route_waits_then_continues_without_resetting_prior_work():
    app, ids, body = living()
    obstacles = state(app, ids).projections.setdefault("tabletop.obstacles", {})
    for i, (x, y) in enumerate(((51, 0), (50, 1), (49, 0), (50, -1))):
        obstacles[str(uuid.UUID(int=i + 100))] = {"x": x, "y": y}
    advance(app, ids, 75)
    assert state(app, ids).projections[ACTIVITIES][body]["reason"] == "PATH_BLOCKED"
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 60
    state(app, ids).projections["tabletop.obstacles"].clear()
    advance(app, ids, 100)
    physical = state(app, ids).projections["tabletop.entities"][body]
    assert physical["travel_steps"] == 2 and physical["sleep_seconds"] == 5
    assert physical["weeded_units"] == 60


def test_food_shortage_interrupts_joint_attendance_and_does_not_complete_it():
    app, ids, body = living(sleep_start=1000, hunger_limit=100)
    state(app, ids).projections["tabletop.entities"][body]["inventory"]["food"] = 0
    partner, identity = meeting(app, ids, body, starts=50, duration=100, grace=100)
    advance(app, ids, 250)
    row = state(app, ids).projections[OBLIGATIONS][identity]
    assert row["status"] == "MISSED" and row["progress_seconds"] == 50
    assert state(app, ids).projections["tabletop.entities"][body]["social_seconds"] == 50
    assert state(app, ids).projections["tabletop.entities"][partner]["social_seconds"] == 50


def test_overlap_validation_allows_distinct_repeating_commitments_but_rejects_conflict():
    app, ids, body = living(sleep_start=1000)
    meeting(app, ids, body, repeat=600)
    meeting(app, ids, body, starts=300, repeat=600)
    before = state(app, ids).state_hash
    with pytest.raises(ValueError, match="overlapping"):
        meeting(app, ids, body, starts=110, repeat=600)
    assert state(app, ids).state_hash == before


@pytest.mark.parametrize("recurring_first", [False, True])
def test_long_oneoff_window_cannot_overlap_first_future_recurring_commitment(recurring_first):
    app, ids, body = living(sleep_start=1000)
    requests = [
        {"starts": 0, "duration": 86400, "grace": 20000, "lead_seconds": 0},
        {"starts": 100000, "duration": 100, "grace": 0, "lead_seconds": 0, "repeat": 600},
    ]
    if recurring_first:
        requests.reverse()
    meeting(app, ids, body, **requests[0])
    before = state(app, ids).state_hash
    with pytest.raises(ValueError, match="overlapping"):
        meeting(app, ids, body, **requests[1])
    assert state(app, ids).state_hash == before


def test_oneoff_ending_at_first_recurrence_start_does_not_overlap():
    from population.life import overlapping

    oneoff = {
        "starts_seconds": 0,
        "duration_seconds": 86400,
        "grace_seconds": 13600,
        "lead_seconds": 0,
    }
    recurring = {
        "starts_seconds": 100000,
        "duration_seconds": 100,
        "grace_seconds": 0,
        "lead_seconds": 0,
        "repeat_seconds": 600,
    }
    assert not overlapping(oneoff, recurring)
    assert not overlapping(recurring, oneoff)


def test_unmanaged_attendance_is_not_double_counted_at_weather_boundaries():
    results = []
    for weather in (False, True):
        app, ids, body = living(sleep_start=1000)
        partner, identity = meeting(app, ids, body, starts=100, duration=40)
        send(
            app,
            ids,
            "tabletop.routine.configure",
            {"entity_id": body, "expected_version": 2, "enabled": False},
            "disable",
        )
        # Both manually controlled participants are already physically at the meeting point.
        state(app, ids).projections["tabletop.spatial.positions"][body]["x"] = 52
        if weather:
            send(
                app,
                ids,
                "tabletop.weather.schedule",
                {"zone_id": "world", "due_seconds": 120, "raining": False},
                "boundary",
            )
        advance(app, ids, 150)
        row = state(app, ids).projections[OBLIGATIONS][identity]
        assert row["completed_count"] == 1 and row["progress_seconds"] == 40
        assert state(app, ids).projections["tabletop.entities"][body]["social_seconds"] == 40
        results.append(row)
    assert results[0] == results[1]


def test_multiple_daily_sleep_windows_preserve_actual_location_and_rest():
    app, ids, body = living(hunger_limit=86400)
    advance(app, ids, 160)
    advance(app, ids, 86400)
    advance(app, ids, 86560)
    body_state = state(app, ids).projections["tabletop.entities"][body]
    assert body_state["sleep_seconds"] == 80 and body_state["travel_steps"] == 8


def test_human_action_wakes_sleeping_body_and_autonomous_proposal_is_suspended():
    from domains.tabletop.spatial import move
    from kernel.contracts import CommandProposal
    from kernel.errors import BodySleeping
    from population.life import wake_after_action

    app, ids, body = living()
    advance(app, ids, 90)
    current = state(app, ids)
    proposal = CommandProposal(
        **ids,
        command_type="tabletop.spatial.move",
        parameters={"dx": 0, "dy": 1},
        embodied_entity_id=body,
        idempotency_key="wake-by-acting",
    )
    before = current.state_hash
    with pytest.raises(BodySleeping):
        wake_after_action(
            proposal.model_copy(update={"decision_authorship": "CHARACTER_POLICY"}), current, move
        )
    assert current.state_hash == before
    result = wake_after_action(proposal, current, move)
    for delta in result.deltas:
        current.apply(delta)
    assert not current.projections["tabletop.entities"][body]["asleep"]
    assert all(delta.projection != ROUTINES for delta in result.deltas)
    advance(app, ids, 100)
    assert current.projections[ROUTINES][body]["awake_until"] == 390


def test_sleeping_policy_runner_preserves_controller_mode_and_budget(monkeypatch, tmp_path):
    from tests.unit.kernel.test_character_binding_api import _app
    from tests.unit.kernel.test_world_time import NOW, api_command, clock_game

    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    clock_path = f"/api/v2/worlds/{base['world_id']}/branches/{base['branch_id']}/clock"
    executor = admin.get(clock_path).get_json()["clock"]["executor_actor_id"]
    api_command(
        admin,
        base,
        "tabletop.clock.configure",
        {
            "expected_epoch": 1,
            "executor_actor_id": executor,
            "wall_time": NOW.isoformat(),
            "paused": False,
        },
        "resume",
    )
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 2,
            "idempotency_key": "leave",
        },
    )
    assert response.status_code == 200
    simulation = app.extensions["simulation"]
    simulation.states.get(uuid.UUID(base["branch_id"])).projections["tabletop.entities"][
        card["entity_id"]
    ]["asleep"] = True
    assert app.extensions["character_runner"].run_once() == 0
    control = player.get(path + "/control", query_string={"run_id": run}).get_json()["control"]
    assert control["mode"] == "AUTONOMOUS" and control["step"] == 0 and control["failures"] == 0


def test_existing_work_routine_can_attend_where_present_without_a_life_plan():
    app, ids, body = living(sleep_start=1000)
    send(
        app,
        ids,
        "tabletop.routine.configure",
        {"entity_id": body, "expected_version": 2, "work_seconds": 120, "rest_seconds": 60},
        "legacy",
    )
    partner, identity = meeting(app, ids, body, place={"x": 50, "y": 0}, radius=2)
    advance(app, ids, 150)
    current = state(app, ids)
    assert current.projections[OBLIGATIONS][identity]["completed_count"] == 1
    assert current.projections["tabletop.entities"][body]["weeded_units"] == 120
    assert current.projections["tabletop.entities"][body]["social_seconds"] == 20
    assert current.projections["tabletop.spatial.positions"][body]["x"] == 50


def test_explicit_urgent_obligation_can_override_sleep_but_normal_one_can_be_missed():
    for urgent in (False, True):
        app, ids, body = living()
        partner, identity = meeting(
            app, ids, body, starts=90, duration=20, grace=0, wake_for_obligation=urgent
        )
        advance(app, ids, 120)
        current = state(app, ids)
        assert current.projections[OBLIGATIONS][identity]["status"] == (
            "COMPLETED" if urgent else "MISSED"
        )
        assert current.projections["tabletop.entities"][body]["sleep_seconds"] == (
            10 if urgent else 60
        )


def test_trial_life_plan_and_attendance_do_not_change_canonical_body():
    from tests.unit.kernel.test_world_time import configure

    app, ids, body = living()
    partner, identity = meeting(app, ids, body)
    before = state(app, ids).state_hash
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    trial, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 44)
    trial_ids = {**ids, "branch_id": trial.branch_id, "run_id": run.run_id}
    configure(app, trial_ids)
    advance(app, trial_ids, 160)
    assert state(app, ids).state_hash == before
    assert state(app, trial_ids).projections[OBLIGATIONS][identity]["completed_count"] == 1
    assert state(app, trial_ids).projections["tabletop.entities"][body]["sleep_seconds"] == 50


def test_two_managed_travelers_attend_together_independent_of_tick_partition():
    from population.lifecycle import PopulationLifecycle

    results = []
    for boundaries in ([150], [50, 60, 70, 100, 110, 120, 140, 150]):
        app, ids, body = living(sleep_start=1000)
        second = uuid.uuid5(uuid.UUID(body), "second-managed-person")
        send(
            app,
            ids,
            "tabletop.entity.spawn",
            {
                "entity_id": str(second),
                "name": "Other gardener",
                "entity_type": "any_class",
                "public_state": {"hp": 100, "x": 54},
            },
            "second",
        )
        source = PopulationLifecycle(ids["world_id"], ids["branch_id"])
        persona = uuid.uuid5(second, "persona")
        member = source.materialize(persona, profile={}, world_step=17)
        reader = app.population_source_reader
        app.population_source_reader = (
            lambda pool, identity, reader=reader, source=source, persona=persona: (
                source.get(identity) if identity == persona else reader(pool, identity)
            )
        )
        send(
            app,
            ids,
            "tabletop.population.bind",
            {
                "population_id": str(uuid.uuid5(second, "pool")),
                "entity_id": str(second),
                "source_member": member.model_dump(mode="json"),
            },
            "second-bind",
        )
        send(
            app,
            ids,
            "tabletop.routine.configure",
            {
                "entity_id": str(second),
                "expected_version": 0,
                "hunger_limit": 10000,
                "fatigue_limit": 10000,
                "work_seconds": 120,
                "rest_seconds": 60,
                "life": {
                    "home": {"x": 54, "y": 0},
                    "workplace": {"x": 54, "y": 0},
                    "step_seconds": 10,
                    "sleep_start_seconds": 1000,
                    "sleep_seconds": 60,
                },
            },
            "second-life",
        )
        send(
            app,
            ids,
            "tabletop.obligation.schedule",
            {
                "participants": [body, str(second)],
                "place": {"x": 52, "y": 0},
                "starts_seconds": 100,
                "duration_seconds": 20,
                "grace_seconds": 30,
                "lead_seconds": 50,
            },
            "joint",
        )
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        for key in (body, str(second)):
            assert current.projections["tabletop.entities"][key]["social_seconds"] == 20
        results.append(outcomes(current))
    assert results[0] == results[1]


def test_inconsistent_timeline_is_rejected_without_negative_elapsed_resources():
    app, ids, body = living()
    state(app, ids).projections[ROUTINES][body]["updated_seconds"] = 100
    before = state(app, ids).state_hash
    with pytest.raises(ValueError, match="time cannot move backward"):
        advance(app, ids, 50)
    assert state(app, ids).state_hash == before

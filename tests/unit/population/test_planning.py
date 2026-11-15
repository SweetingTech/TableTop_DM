from __future__ import annotations

import uuid

import pytest

from domains.tabletop.activities import ACTIVITIES
from population.routines import ROUTINES
from tests.unit.kernel.test_world_time import advance, send
from tests.unit.population.test_life import living, meeting, outcomes
from tests.unit.population.test_runtime import state

pytestmark = pytest.mark.unit


def configure_game_plan(app, game):
    from tests.unit.kernel.test_world_time import api_command
    from tests.unit.population.test_life import configure_game_life

    configure_game_life(app, game)
    admin, player, card, path, run, target, base = game
    config = {
        "entity_id": target,
        "expected_version": 2,
        "hunger_limit": 10000,
        "fatigue_limit": 10000,
        "life": {
            "home": {"x": 3, "y": 0},
            "workplace": {"x": 1, "y": 0},
            "step_seconds": 10,
            "sleep_start_seconds": 10000,
            "sleep_seconds": 60,
            "planning": {
                "retry_seconds": 30,
                "goals": [
                    {
                        "goal_id": "private_garden_goal",
                        "kind": "WEED",
                        "place": {"x": 1, "y": 0},
                        "seconds_per_day": 120,
                        "priority": 80,
                    },
                    {
                        "goal_id": "private_reading_goal",
                        "kind": "REST",
                        "place": {"x": 3, "y": 0},
                        "seconds_per_day": 60,
                        "priority": 20,
                    },
                ],
            },
        },
    }
    api_command(admin, base, "tabletop.routine.configure", config, "daily-config")
    return config


def planning_life(*, goals=None, **changes):
    app, ids, body = living(sleep_start=10000)
    configure_plan(app, ids, body, goals=goals, **changes)
    return app, ids, body


def configure_plan(app, ids, body, *, goals=None, **changes):
    row = state(app, ids).projections[ROUTINES][body]
    place = row["life"]["workplace"]
    return send(
        app,
        ids,
        "tabletop.routine.configure",
        {
            "entity_id": body,
            "expected_version": row["version"],
            "work_seconds": 120,
            "rest_seconds": 60,
            "hunger_limit": 86400,
            "fatigue_limit": 10000,
            "life": {
                **row["life"],
                "planning": {
                    "retry_seconds": 30,
                    "goals": goals
                    if goals is not None
                    else [
                        {
                            "goal_id": "garden",
                            "kind": "WEED",
                            "place": place,
                            "seconds_per_day": 120,
                            "priority": 80,
                        },
                        {
                            "goal_id": "recreation",
                            "kind": "REST",
                            "place": row["life"]["home"],
                            "seconds_per_day": 60,
                            "priority": 20,
                        },
                    ],
                },
            },
            **changes,
        },
        "daily:" + str(row["version"]),
    )


def test_daily_goals_finish_then_rest_without_inventing_more_work_partition_invariant():
    results = []
    for boundaries in ([300], [1, 30, 47, 90, 119, 120, 125, 130, 140, 199, 200, 260, 300]):
        app, ids, body = planning_life()
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        assert current.projections["tabletop.entities"][body]["weeded_units"] == 120
        row = current.projections[ROUTINES][body]
        assert row["planner"]["spent"] == {"garden": 120, "recreation": 60}
        assert row["planner"]["reason"] == "DAY_COMPLETE"
        results.append(outcomes(current))
        assert app.replay(ids["branch_id"]).state_hash == current.state_hash
    assert results[0] == results[1]


def test_rain_shelter_and_resume_preserve_partial_goal_across_irrelevant_weather_splits():
    results = []
    for split in (False, True):
        app, ids, body = planning_life()
        for due, raining in ((40, True), (110, False)):
            send(
                app,
                ids,
                "tabletop.weather.schedule",
                {"zone_id": "world", "due_seconds": due, "raining": raining},
                str(due),
            )
        if split:
            send(
                app,
                ids,
                "tabletop.weather.schedule",
                {"zone_id": "world", "due_seconds": 63, "raining": True},
                "elsewhere",
            )
            advance(app, ids, 75)
        advance(app, ids, 300)
        current = state(app, ids)
        assert current.projections["tabletop.entities"][body]["weeded_units"] == 120
        assert current.projections[ROUTINES][body]["planner"]["spent"]["garden"] == 120
        results.append(outcomes(current))
    assert results[0] == results[1]


def test_manual_displacement_returns_to_goal_without_operator_reconfiguration():
    app, ids, body = planning_life()
    advance(app, ids, 40)
    state(app, ids).projections.setdefault("tabletop.spatial.positions", {}).setdefault(
        body, {"x": 50, "y": 0}
    )["x"] = 53
    advance(app, ids, 50)
    assert state(app, ids).projections[ACTIVITIES][body]["kind"] == "TRAVEL"
    advance(app, ids, 200)
    current = state(app, ids)
    assert current.projections["tabletop.entities"][body]["weeded_units"] == 120
    assert current.projections[ROUTINES][body]["planner"]["spent"]["garden"] == 120


def test_injury_seeks_home_then_recovers_without_operator_reconfiguration():
    app, ids, body = planning_life()
    advance(app, ids, 40)
    state(app, ids).projections["tabletop.entities"][body]["hp"] = 90
    advance(app, ids, 60)
    current = state(app, ids)
    assert current.projections["tabletop.spatial.positions"][body]["x"] == 52
    assert current.projections[ACTIVITIES][body]["kind"] == "REST"
    assert current.projections[ROUTINES][body]["planner"]["reason"] == "INJURY"
    advance(app, ids, 500)
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 120


def test_daily_quota_resets_once_and_state_stays_bounded_across_days():
    results = []
    for boundaries in ([86400, 86800], [100, 200, 85000, 86400, 86401, 86500, 86800]):
        app, ids, body = planning_life()
        state(app, ids).projections["tabletop.entities"][body]["inventory"]["food"] = 100
        for until in boundaries:
            advance(app, ids, until)
        current = state(app, ids)
        assert current.projections["tabletop.entities"][body]["weeded_units"] == 240
        row = current.projections[ROUTINES][body]
        assert row["planner"]["day"] == 1
        assert len(row["suspended"]) <= 18
        results.append(outcomes(current))
    assert results[0] == results[1]


def test_food_shortage_seeks_home_and_real_replenishment_resumes_goals():
    app, ids, body = planning_life(hunger_limit=60)
    state(app, ids).projections["tabletop.entities"][body]["inventory"]["food"] = 0
    advance(app, ids, 100)
    current = state(app, ids)
    assert current.projections["tabletop.spatial.positions"][body]["x"] == 52
    assert current.projections[ROUTINES][body]["planner"]["reason"] == "NO_FOOD"
    assert current.projections["tabletop.entities"][body]["weeded_units"] == 60
    current.projections["tabletop.entities"][body]["inventory"]["food"] = 1
    advance(app, ids, 140)
    physical = state(app, ids).projections["tabletop.entities"][body]
    assert physical["inventory"]["food"] == 0 and physical["meals_eaten"] == 1
    assert physical["weeded_units"] > 60


def test_unreachable_goal_chooses_available_alternative_then_retries():
    app, ids, body = planning_life(
        goals=[
            {
                "goal_id": "distant",
                "kind": "WEED",
                "place": {"x": 53, "y": 0},
                "seconds_per_day": 60,
                "priority": 100,
            },
            {
                "goal_id": "local",
                "kind": "WEED",
                "place": {"x": 50, "y": 0},
                "seconds_per_day": 60,
                "priority": 10,
            },
        ]
    )
    obstacles = state(app, ids).projections.setdefault("tabletop.obstacles", {})
    for i, (x, y) in enumerate(((51, 0), (50, 1), (49, 0), (50, -1))):
        obstacles[str(uuid.UUID(int=i + 1))] = {"x": x, "y": y}
    advance(app, ids, 20)
    assert state(app, ids).projections["tabletop.entities"][body]["weeded_units"] == 20
    state(app, ids).projections["tabletop.obstacles"].clear()
    advance(app, ids, 160)
    row = state(app, ids).projections[ROUTINES][body]
    assert row["planner"]["spent"] == {"local": 60, "distant": 60}


def test_real_obligation_still_preempts_goal_and_resumes_it():
    app, ids, body = planning_life()
    _, identity = meeting(app, ids, body)
    advance(app, ids, 300)
    current = state(app, ids)
    assert current.projections["tabletop.obligations"][identity]["completed_count"] == 1
    assert current.projections[ROUTINES][body]["planner"]["spent"]["garden"] == 120


def test_daily_plan_validation_rejects_duplicate_goals_and_foreign_zone_atomically():
    app, ids, body = planning_life()
    for goals in (
        [{"goal_id": "x", "kind": "REST", "place": {"x": 50, "y": 0}}] * 2,
        [{"goal_id": "x", "kind": "REST", "place": {"x": 50, "y": 0, "zone_id": "foreign"}}],
    ):
        before = state(app, ids).state_hash
        with pytest.raises(ValueError):
            configure_plan(app, ids, body, goals=goals)
        assert state(app, ids).state_hash == before


def test_fatigue_mid_commute_and_rest_recovery_are_partition_invariant():
    results = []
    for boundaries in ([250], [1, 2, 7, 13, 30, 61, 62, 75, 100, 150, 250]):
        app, ids, body = planning_life(
            goals=[
                {
                    "goal_id": "remote",
                    "kind": "WEED",
                    "place": {"x": 53, "y": 0},
                    "seconds_per_day": 60,
                    "priority": 100,
                }
            ],
            fatigue_limit=60,
        )
        state(app, ids).projections["tabletop.entities"][body]["fatigue"] = 59
        for until in boundaries:
            advance(app, ids, until)
        results.append(outcomes(state(app, ids)))
    assert results[0] == results[1]


def test_midroute_obstruction_switches_to_feasible_goal_and_retries_after_recovery():
    app, ids, body = planning_life(
        goals=[
            {
                "goal_id": "remote",
                "kind": "WEED",
                "place": {"x": 53, "y": 0},
                "seconds_per_day": 60,
                "priority": 100,
            },
            {
                "goal_id": "local",
                "kind": "REST",
                "place": {"x": 51, "y": 0},
                "seconds_per_day": 40,
                "priority": 10,
            },
        ]
    )
    advance(app, ids, 10)
    obstacles = state(app, ids).projections.setdefault("tabletop.obstacles", {})
    for i, (x, y) in enumerate(((52, 0), (51, 1), (50, 0), (51, -1))):
        obstacles[str(uuid.UUID(int=i + 1))] = {"x": x, "y": y}
    advance(app, ids, 25)
    # The obstruction selects the viable local goal at the same simulated instant.
    advance(app, ids, 55)
    assert state(app, ids).projections[ROUTINES][body]["planner"]["spent"]["local"] == 40
    state(app, ids).projections["tabletop.obstacles"].clear()
    advance(app, ids, 200)
    assert state(app, ids).projections[ROUTINES][body]["planner"]["spent"]["remote"] == 60


def test_goal_preferences_and_stable_ties_change_actual_choices():
    for priority, expected in ((90, "z_remote"), (10, "a_local")):
        app, ids, body = planning_life(
            goals=[
                {
                    "goal_id": "z_remote",
                    "kind": "WEED",
                    "place": {"x": 53, "y": 0},
                    "seconds_per_day": 60,
                    "priority": priority,
                },
                {
                    "goal_id": "a_local",
                    "kind": "REST",
                    "place": {"x": 50, "y": 0},
                    "seconds_per_day": 60,
                    "priority": 50,
                },
            ]
        )
        advance(app, ids, 1)
        assert state(app, ids).projections[ROUTINES][body]["planner"]["selected"] == expected


def test_daily_planning_trial_keeps_canonical_state_isolated():
    from tests.unit.kernel.test_world_time import configure

    app, ids, body = planning_life()
    before = state(app, ids).state_hash
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    trial, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 44)
    trial_ids = {**ids, "branch_id": trial.branch_id, "run_id": run.run_id}
    configure(app, trial_ids)
    advance(app, trial_ids, 300)
    assert state(app, ids).state_hash == before
    assert state(app, trial_ids).projections[ROUTINES][body]["planner"]["spent"]["garden"] == 120


def test_missing_food_preempts_an_appointment_without_inventing_attendance():
    app, ids, body = planning_life(hunger_limit=60)
    state(app, ids).projections["tabletop.entities"][body]["inventory"]["food"] = 0
    _, identity = meeting(app, ids, body, starts=50, duration=100, grace=100)
    advance(app, ids, 260)
    current = state(app, ids)
    row = current.projections["tabletop.obligations"][identity]
    assert row["status"] == "MISSED" and row["progress_seconds"] == 10
    assert current.projections[ROUTINES][body]["planner"]["reason"] == "NO_FOOD"


@pytest.mark.parametrize("cause", ["NO_FOOD", "INJURY", "DAY_COMPLETE"])
def test_homeward_steps_survive_retry_slots_shorter_than_travel(cause):
    results = []
    for split in (False, True):
        app, ids, body = planning_life(
            goals=[
                {
                    "goal_id": "brief_work",
                    "kind": "WEED",
                    "place": {"x": 50, "y": 0},
                    "seconds_per_day": 1,
                    "priority": 50,
                }
            ]
        )
        row = state(app, ids).projections[ROUTINES][body]
        configure_plan(
            app,
            ids,
            body,
            life={
                **row["life"],
                "step_seconds": 60,
                "planning": {**row["life"]["planning"], "retry_seconds": 10},
            },
        )
        physical = state(app, ids).projections["tabletop.entities"][body]
        if cause == "NO_FOOD":
            physical["inventory"]["food"] = 0
            physical["hunger"] = 86400
        advance(app, ids, 1)
        if cause == "INJURY":
            state(app, ids).projections["tabletop.entities"][body]["hp"] = 90
        for until in [2, 9, 10, 30, 59, 60, 61, 90, 119, 120, 121, 140, 200] if split else [200]:
            advance(app, ids, until)
        current = state(app, ids)
        assert current.projections["tabletop.spatial.positions"][body]["x"] == 52
        assert current.projections["tabletop.entities"][body]["travel_steps"] == 2
        assert current.projections[ROUTINES][body]["planner"]["reason"] == cause
        results.append(outcomes(current))
    assert results[0] == results[1]

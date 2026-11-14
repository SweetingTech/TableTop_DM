from __future__ import annotations

from datetime import timedelta

import pytest

from domains.tabletop.activities import ACTIVITIES
from kernel.application import stable_id
from tests.unit.kernel.test_world_time import NOW, advance, configure, reference, send

pytestmark = pytest.mark.unit


def garden():
    app, ids = reference()
    configure(app, ids)
    body = stable_id("demo:entity:hero")
    receipt = send(
        app,
        ids,
        "tabletop.activity.start",
        {"entity_id": str(body), "kind": "WEED", "duration_seconds": 10},
        "start",
    )
    return app, ids, body, receipt


def test_gardener_keeps_working_without_observers_and_rain_splits_elapsed_time():
    results = []
    for split in (False, True):
        app, ids, body, _ = garden()
        for due, rain in ((3, True), (7, False)):
            send(
                app,
                ids,
                "tabletop.weather.schedule",
                {"due_seconds": due, "zone_id": "world", "raining": rain},
                f"weather:{due}",
            )
        if split:
            advance(app, ids, 5)
            waiting = app.states.get(ids["branch_id"]).projections[ACTIVITIES][str(body)]
            assert waiting["status"] == "WAITING" and waiting["progress_seconds"] == 3
        advance(app, ids, 10)
        state = app.states.get(ids["branch_id"])
        assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 6
        assert not state.projections["tabletop.weather_schedule"]
        assert state.projections[ACTIVITIES][str(body)]["progress_seconds"] == 6
        results.append((state.projections[ACTIVITIES], state.projections["tabletop.entities"]))
        assert not app.perceptions
    assert results[0] == results[1]


def test_activity_completion_and_cancel_do_not_duplicate_work():
    app, ids, body, started = garden()
    advance(app, ids, 20)
    state = app.states.get(ids["branch_id"])
    assert state.projections[ACTIVITIES][str(body)]["status"] == "COMPLETED"
    assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 10
    advance(app, ids, 30)
    assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 10
    second = send(
        app,
        ids,
        "tabletop.activity.start",
        {"entity_id": str(body), "kind": "WEED", "duration_seconds": 20},
        "second",
    )
    with pytest.raises(ValueError):
        send(
            app,
            ids,
            "tabletop.activity.cancel",
            {"entity_id": str(body), "activity_id": started.result.result["activity_id"]},
            "stale-cancel",
        )
    send(
        app,
        ids,
        "tabletop.activity.cancel",
        {"entity_id": str(body), "activity_id": second.result.result["activity_id"]},
        "cancel",
    )
    advance(app, ids, 40)
    assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 10


@pytest.mark.parametrize("interruption", ["move", "incapacity"])
def test_physical_changes_interrupt_pending_work(interruption):
    app, ids, body, _ = garden()
    advance(app, ids, 3)
    if interruption == "move":
        send(
            app, ids, "tabletop.spatial.move", {"dx": 0, "dy": -1}, "move", embodied_entity_id=body
        )
    else:
        attacker = stable_id("demo:entity:wolf")
        app.assign_control(ids["world_id"], ids["actor_id"], attacker)
        send(
            app,
            ids,
            "tabletop.combat.attack",
            {"target_id": str(body), "attack_bonus": 30, "damage_bonus": 100},
            "kill",
            embodied_entity_id=attacker,
            seed=2,
        )
    advance(app, ids, 7)
    state = app.states.get(ids["branch_id"])
    assert state.projections[ACTIVITIES][str(body)]["status"] == "WAITING"
    assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 3


def test_weather_cancellation_and_same_time_order_are_stable():
    app, ids, body, _ = garden()
    pending = send(
        app,
        ids,
        "tabletop.weather.schedule",
        {"due_seconds": 0, "zone_id": "world", "raining": True},
        "rain",
    )
    send(
        app,
        ids,
        "tabletop.weather.cancel",
        {"schedule_id": pending.result.result["schedule_id"]},
        "cancel-weather",
    )
    for name, value in (("first", True), ("second", False)):
        send(
            app,
            ids,
            "tabletop.weather.schedule",
            {"due_seconds": 2, "zone_id": "world", "raining": value},
            name,
        )
    advance(app, ids, 5)
    assert (
        app.states.get(ids["branch_id"]).projections["tabletop.entities"][str(body)]["weeded_units"]
        == 5
    )
    with pytest.raises(ValueError):
        send(
            app,
            ids,
            "tabletop.weather.schedule",
            {"due_seconds": 1, "zone_id": "world", "raining": True},
            "past",
        )


def test_rest_uses_same_clock_and_caps_fatigue_at_zero():
    app, ids = reference()
    configure(app, ids)
    body = stable_id("demo:entity:hero")
    app.states.get(ids["branch_id"]).projections["tabletop.entities"][str(body)]["fatigue"] = 3
    send(
        app,
        ids,
        "tabletop.activity.start",
        {"entity_id": str(body), "kind": "REST", "duration_seconds": 5},
        "rest",
    )
    advance(app, ids, 10)
    assert (
        app.states.get(ids["branch_id"]).projections["tabletop.entities"][str(body)]["fatigue"] == 0
    )


def test_clock_tick_progresses_activity_and_action_does_not_double_advance_time():
    from kernel.world_runner import WorldRunner

    app, ids, body, _ = garden()
    configure(app, ids, paused=False, seconds_per_tick=2)
    runner = WorldRunner(lambda: app)
    assert runner.run_once(NOW + timedelta(seconds=1)) == 1
    send(app, ids, "tabletop.dialogue.speak", {"text": "Hello"}, "speech", embodied_entity_id=body)
    assert runner.run_once(NOW + timedelta(seconds=2)) == 1
    state = app.states.get(ids["branch_id"])
    assert state.projections["tabletop.clock"]["singleton"]["seconds"] == 4
    assert state.projections["tabletop.entities"][str(body)]["weeded_units"] == 4


def test_new_trial_schedule_stays_after_copied_same_time_work():
    app, ids, body, _ = garden()
    send(
        app,
        ids,
        "tabletop.weather.schedule",
        {"due_seconds": 2, "zone_id": "world", "raining": True},
        "inherited-rain",
    )
    snapshot = app.create_branch_snapshot(ids["branch_id"])
    branch, run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 37)
    scoped = {**ids, "branch_id": branch.branch_id, "run_id": run.run_id}
    configure(app, scoped)
    send(
        app,
        scoped,
        "tabletop.weather.schedule",
        {"due_seconds": 2, "zone_id": "world", "raining": False},
        "later-clear",
    )
    advance(app, scoped, 5)
    assert branch.projections["tabletop.entities"][str(body)]["weeded_units"] == 5
    assert (
        "weeded_units"
        not in app.states.get(ids["branch_id"]).projections["tabletop.entities"][str(body)]
    )

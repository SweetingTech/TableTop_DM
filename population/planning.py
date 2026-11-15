"""Private, bounded daily choices executed by the authorized world clock.

Inputs are bodily needs, configured intentions and local physical affordances.
This policy does not read another person's hidden state or write subjective cognition.
"""

from __future__ import annotations

from cognition.goal_motivation import GoalMotivation
from domains.tabletop.activities import ACTIVITIES, WEATHER, Activity, position
from kernel.state import BranchState
from population.life import DAY, due_obligation, route, sleeping, switch, travel

POLICY_VERSION = "npc-daily-planning-1.1.0"


def prepare_plan(state: BranchState, key: str, row: dict, now: int) -> None:
    body = state.projections["tabletop.entities"][key]
    plan = row["life"]
    options = plan["planning"]
    motivation = (
        GoalMotivation.model_validate(row["motivation"]) if options.get("motivated") else None
    )
    motivation_hash = motivation.input_hash if motivation else None
    old = Activity.model_validate(state.projections[ACTIVITIES][key])
    actual = position(state, key)
    day = now // DAY
    planner = row.setdefault("planner", {})
    if planner.get("day") != day:
        planner.update(day=day, spent={}, selected=None, blocked={})
        row["suspended"] = {
            task: raw
            for task, raw in row["suspended"].items()
            if not task.startswith(("goal:", "travel:goal:"))
        }
    planner["policy_version"] = POLICY_VERSION
    planner["blocked"] = {task: until for task, until in planner["blocked"].items() if until > now}
    allowed_cache = {"meal", "need:rest", "travel:homeward"} | {
        prefix + f"goal:{day}:{goal['goal_id']}"
        for goal in options["goals"]
        for prefix in ("", "travel:")
    }
    row["suspended"] = {
        task: raw for task, raw in row["suspended"].items() if task in allowed_cache
    }
    if int(body.get("hp", 0)) <= 0:
        body["asleep"] = row["was_asleep"] = False
        state.projections[ACTIVITIES][key] = old.model_copy(
            update={"updated_seconds": now, "status": "WAITING", "reason": "INCAPACITATED"}
        ).model_dump(mode="json")
        return

    due = due_obligation(state, key, now)
    raining = state.projections.get(WEATHER, {}).get("singleton", {}).get(actual["zone_id"], False)
    danger = now < row.get("awake_until", 0)
    night = sleeping(plan, now) and not (due and due[1]["wake_for_obligation"])
    hungry = int(body.get("hunger", 0)) >= row["hunger_limit"]
    food = int(body.get("inventory", {}).get("food", 0)) > 0
    tired = int(body.get("fatigue", 0)) >= row["fatigue_limit"] or (
        old.task_key == "need:rest" and old.status != "COMPLETED"
    )
    interval = options["retry_seconds"]
    slot = now // interval

    def choose(task: str, kind: str, place: dict, duration: int, reason: str, details=None):
        if (
            motivation
            and place == plan["home"]
            and place in motivation.unsafe_places
            and task.startswith(("fallback:", "safe:", "sleep:"))
        ):
            task, kind, place, duration, reason = (
                f"fallback:{slot}",
                "REST",
                actual,
                interval,
                "BELIEVED_DANGER",
            )
        if actual != place:
            # Retry slots rotate rest decisions, not an unfinished physical journey.
            travel_task = (
                "homeward"
                if place == plan["home"] and task.startswith(("fallback:", "safe:", "sleep:"))
                else task
            )
            activity = travel(state, key, row, travel_task, place, now)
        else:
            activity = switch(state, key, row, task, kind, now, duration, details)
        return activity, reason

    if danger:
        activity, reason = choose(f"safe:{slot}", "REST", plan["home"], interval, "INJURY")
    elif night:
        remaining = plan["sleep_seconds"] - (now - plan["sleep_start_seconds"]) % DAY
        activity, reason = choose(
            f"sleep:{(now - plan['sleep_start_seconds']) // DAY}",
            "SLEEP",
            plan["home"],
            remaining,
            "SLEEP",
        )
    elif hungry and food:
        activity, reason = choose("meal", "EAT", actual, row["meal_seconds"], "HUNGER")
    elif hungry:
        activity, reason = choose(f"fallback:{slot}", "REST", plan["home"], interval, "NO_FOOD")
    elif tired:
        activity, reason = choose("need:rest", "REST", actual, row["rest_seconds"], "FATIGUE")
    elif due:
        identity, obligation = due
        activity, reason = choose(
            f"social:{identity}:{obligation['occurrence']}",
            "SOCIAL",
            obligation["place"],
            obligation["duration_seconds"],
            "OBLIGATION",
            {"obligation_id": identity},
        )
    else:
        goals = []
        for goal in options["goals"]:
            identity = goal["goal_id"]
            if motivation and identity in motivation.avoided:
                continue
            if planner["spent"].get(identity, 0) >= goal["seconds_per_day"]:
                continue
            if goal["kind"] == "WEED" and raining:
                continue
            if planner["blocked"].get(identity, 0) > now:
                continue
            goal_task = f"goal:{day}:{identity}"
            ongoing = old.task_key in {goal_task, "travel:" + goal_task} and old.status not in {
                "COMPLETED",
                "CANCELLED",
            }
            ongoing = ongoing and motivation_hash == planner.get("motivation_hash")
            expected = old.details.get("expected") if old.kind == "TRAVEL" else old.origin
            obstructed = False
            if ongoing and old.kind == "TRAVEL":
                path, index = old.details["path"], old.details["index"]
                blocked = {
                    (int(item["x"]), int(item["y"]))
                    for item in state.projections.get("tabletop.obstacles", {}).values()
                }
                obstructed = not path or (
                    index < len(path) and (path[index]["x"], path[index]["y"]) in blocked
                )
            if (
                actual != goal["place"]
                and (not ongoing or actual != expected or obstructed)
                and not route(state, key, goal["place"])
            ):
                planner["blocked"][identity] = (slot + 1) * interval
                continue
            # Finish a selected feasible goal before scoring the remaining intentions.
            distance = sum(abs(actual[axis] - goal["place"][axis]) for axis in ("x", "y"))
            priority = motivation.priorities[identity] if motivation else goal["priority"]
            goals.append((not ongoing, -priority, distance, identity, goal))
        if goals:
            *_, identity, goal = min(goals)
            planner["selected"] = identity
            planner["motivation_hash"] = motivation_hash
            activity, reason = choose(
                f"goal:{day}:{identity}",
                goal["kind"],
                goal["place"],
                goal["seconds_per_day"],
                "DAILY_GOAL",
                {"planning_goal": identity},
            )
        else:
            reason = (
                "RAIN"
                if raining
                else "BELIEF_AVOIDANCE"
                if motivation and motivation.avoided
                else "DAY_COMPLETE"
            )
            activity, reason = choose(f"fallback:{slot}", "REST", plan["home"], interval, reason)

    activity = activity.model_copy(update={"status": "RUNNING", "reason": None})
    expected = activity.details.get("expected") if activity.kind == "TRAVEL" else activity.origin
    if activity.kind == "TRAVEL":
        details = dict(activity.details)
        path, index = details["path"], details["index"]
        blocked = {
            (int(item["x"]), int(item["y"]))
            for item in state.projections.get("tabletop.obstacles", {}).values()
        }
        if (
            actual != expected
            or not path
            or (index < len(path) and (path[index]["x"], path[index]["y"]) in blocked)
        ):
            replacement = route(state, key, details["goal"])
            details.update(path=replacement, index=0, step_progress=0, expected=actual)
            activity = activity.model_copy(
                update={
                    "progress_seconds": 0,
                    "duration_seconds": max(1, len(replacement) * plan["step_seconds"]),
                    "details": details,
                }
            )
            if not replacement:
                activity = activity.model_copy(
                    update={"status": "WAITING", "reason": "PATH_BLOCKED"}
                )
    elif actual != expected:
        # A displaced rest/meal is a fresh physical action; never abandon the body at an old origin.
        activity = activity.model_copy(update={"origin": actual})
    if activity.reason != "PATH_BLOCKED":
        activity = activity.model_copy(update={"status": "RUNNING", "reason": None})
    decision = (activity.task_key, reason, motivation_hash)
    if tuple(planner.get("decision", ())) != decision:
        planner["decision_sequence"] = planner.get("decision_sequence", 0) + 1
        planner.update(decision=list(decision), decided_seconds=now, reason=reason)
    body["asleep"] = row["was_asleep"] = activity.kind == "SLEEP"
    row["suspended"] = {
        task: raw for task, raw in row["suspended"].items() if task in allowed_cache
    }
    state.projections[ACTIVITIES][key] = activity.model_copy(
        update={"updated_seconds": now}
    ).model_dump(mode="json")

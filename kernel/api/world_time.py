"""Privileged time/activity inspection; normal typed commands perform every mutation."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from flask import Flask, jsonify

from domains.tabletop.activities import ACTIVITIES, SCHEDULE, WEATHER
from domains.tabletop.world_time import read_clock
from kernel.application import SimulationApplication


def register_world_time(
    app: Flask,
    snapshot: Callable[[], SimulationApplication],
    current_actor_id: Callable[[], uuid.UUID],
    require_world_access: Callable,
) -> None:
    @app.get("/api/v2/worlds/<uuid:world_id>/branches/<uuid:branch_id>/clock")
    def world_clock(world_id: uuid.UUID, branch_id: uuid.UUID):
        source = snapshot()
        require_world_access(world_id, source)
        authority = source.authority(world_id, current_actor_id())
        if "entity.control" not in authority.capabilities:
            raise PermissionError("clock inspection requires world management authority")
        state = source.states.get(branch_id)
        if state.world_id != world_id:
            raise ValueError("branch does not belong to world")
        clock = read_clock(state)
        response = jsonify(
            {
                "clock": clock.model_dump(mode="json") if clock else None,
                "activities": state.projections.get(ACTIVITIES, {}),
                "weather": state.projections.get(WEATHER, {}).get("singleton", {}),
                "pending_weather": state.projections.get(SCHEDULE, {}),
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

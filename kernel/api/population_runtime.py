"""Population API bridge; every live lifecycle change crosses the typed kernel."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from flask import Flask, jsonify, request
from pydantic import BaseModel, ConfigDict, Field

from kernel.application import SimulationApplication
from kernel.contracts import CommandProposal
from population.models import PopulationMember
from population.routines import ROUTINES
from population.runtime import HISTORY, MEMBERS, scoped_member


class BindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID
    run_id: uuid.UUID
    expected_source_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=200)


class PopulationRuntime:
    def __init__(
        self,
        simulation: SimulationApplication,
        snapshot: Callable[[], SimulationApplication],
        actor_id: Callable[[], uuid.UUID],
        require_access: Callable,
        source_reader: Callable[[uuid.UUID, uuid.UUID], PopulationMember],
    ) -> None:
        self.simulation = simulation
        self.snapshot = snapshot
        self.actor_id = actor_id
        self.require_access = require_access
        self.source_reader = source_reader
        simulation.population_source_reader = source_reader

    def state(self, record: dict):
        source = self.snapshot()
        world, branch = uuid.UUID(str(record["world_id"])), uuid.UUID(str(record["branch_id"]))
        self.require_access(world, source)
        state = source.states.get(branch)
        if state.world_id != world:
            raise ValueError("population branch belongs to another world")
        return source, state

    def bound(self, record: dict, persona_id: uuid.UUID) -> PopulationMember | None:
        _, state = self.state(record)
        row = state.projections.get(MEMBERS, {}).get(str(persona_id))
        if row is None:
            return None
        if row["population_id"] != str(record["population_id"]):
            raise ValueError("population identity belongs to another pool")
        return scoped_member(state, row["member"])

    def overlay(self, record: dict) -> dict:
        _, state = self.state(record)
        active = set(record["_active_ids"])
        for identity, row in state.projections.get(MEMBERS, {}).items():
            if row["population_id"] != str(record["population_id"]):
                continue
            active.discard(identity)
            if row["member"]["level"] == "ACTIVE":
                active.add(identity)
        return {**record, "active": len(active), "_active_ids": sorted(active)}

    def change_level(self, record: dict, member: PopulationMember, level: str) -> PopulationMember:
        source, state = self.state(record)
        # Legacy routes have no run field. The branch clock owns the current timeline.
        clock_run = state.projections.get("tabletop.clock", {}).get("singleton", {}).get("run_id")
        runs = sorted(
            (
                run
                for run in source.runs.values()
                if run.world_id == state.world_id
                and run.branch_id == state.branch_id
                and run.kind.value == "LIVE"
                and run.status in {"ACTIVE", "RUNNING"}
                and str(run.run_id) == clock_run
            ),
            key=lambda run: (run.started_at, str(run.run_id)),
        )
        if len(runs) != 1:
            raise ValueError(
                "bound lifecycle requires the clock's active live run; use typed commands"
            )
        self.simulation.submit(
            CommandProposal(
                world_id=state.world_id,
                branch_id=state.branch_id,
                run_id=runs[0].run_id,
                actor_id=self.actor_id(),
                command_type="tabletop.population.level",
                idempotency_key=f"population-level:{member.persona_id}:{member.version}:{level}",
                parameters={
                    "persona_id": str(member.persona_id),
                    "expected_version": member.version,
                    "level": level,
                    "relevance": level,
                },
                input_origin="OPERATOR",
            )
        )
        refreshed = self.bound(record, member.persona_id)
        assert refreshed is not None
        return refreshed


def register_population_runtime(app: Flask, bridge: PopulationRuntime, populations: dict) -> None:
    @app.post("/api/v2/populations/<uuid:population_id>/members/<uuid:persona_id>/bind")
    def bind_population_body(population_id: uuid.UUID, persona_id: uuid.UUID):
        body = BindBody.model_validate(request.get_json(silent=True) or {})
        record = populations[population_id]
        _, state = bridge.state(record)
        member = bridge.source_reader(population_id, persona_id)
        if member.version != body.expected_source_version:
            raise ValueError("population source version changed")
        receipt = bridge.simulation.submit(
            CommandProposal(
                world_id=state.world_id,
                branch_id=state.branch_id,
                run_id=body.run_id,
                actor_id=bridge.actor_id(),
                command_type="tabletop.population.bind",
                idempotency_key=body.idempotency_key,
                parameters={
                    "population_id": str(population_id),
                    "entity_id": str(body.entity_id),
                    "source_member": member.model_dump(mode="json"),
                },
                input_origin="OPERATOR",
            )
        )
        return jsonify(
            {
                "result": receipt.result.model_dump(mode="json"),
                "event": receipt.event.model_dump(mode="json"),
                "state_hash": receipt.state_hash,
            }
        )

    @app.get("/api/v2/worlds/<uuid:world_id>/branches/<uuid:branch_id>/population")
    def inspect_population_runtime(world_id: uuid.UUID, branch_id: uuid.UUID):
        source = bridge.snapshot()
        bridge.require_access(world_id, source)
        if "entity.control" not in source.authority(world_id, bridge.actor_id()).capabilities:
            raise PermissionError("population runtime requires world management authority")
        state = source.states.get(branch_id)
        if state.world_id != world_id:
            raise ValueError("branch belongs to another world")
        response = jsonify(
            {
                "members": state.projections.get(MEMBERS, {}),
                "routines": state.projections.get(ROUTINES, {}),
                "obligations": state.projections.get("tabletop.obligations", {}),
                "transitions": state.projections.get(HISTORY, {}),
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

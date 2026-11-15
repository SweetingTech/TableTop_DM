"""Inject trusted subjective inputs into typed physical planning commands."""

from __future__ import annotations

from collections.abc import Callable

from cognition.goal_motivation import GoalMotivation
from kernel.command_bus import CommandHandler
from kernel.contracts import CommandProposal
from kernel.state import BranchState
from population.runtime import projection_deltas

GoalInputReader = Callable[[CommandProposal, BranchState], dict[str, GoalMotivation]]


def with_motivation(handler: CommandHandler, reader: GoalInputReader | None) -> CommandHandler:
    def execute(proposal, state):
        working = state.working_copy()

        def refresh():
            required = {
                key
                for key, row in working.projections.get("tabletop.routines", {}).items()
                if row["enabled"]
                and (row.get("life") or {}).get("planning")
                and row["life"]["planning"].get("motivated")
            }
            if not required:
                return
            if reader is None:
                raise ValueError("trusted NPC goal reader is unavailable")
            inputs = reader(proposal, working)
            if set(inputs) != required:
                raise ValueError("trusted NPC goal inputs are incomplete")
            for key in sorted(required):
                value = inputs[key]
                if tuple(
                    map(str, (value.world_id, value.branch_id, value.run_id, value.entity_id))
                ) != tuple(map(str, (proposal.world_id, proposal.branch_id, proposal.run_id, key))):
                    raise ValueError("NPC goal input lineage differs from this clock")
                goals = working.projections["tabletop.routines"][key]["life"]["planning"]["goals"]
                if set(value.priorities) != {goal["goal_id"] for goal in goals}:
                    raise ValueError("NPC goal inputs differ from the configured affordances")
                working.projections["tabletop.routines"][key]["motivation"] = inputs[
                    key
                ].model_dump(mode="json")

        if proposal.command_type != "tabletop.routine.configure":
            refresh()
        result = handler(proposal, working)
        for delta in result.deltas:
            working.apply(delta)
        if proposal.command_type == "tabletop.routine.configure":
            refresh()
        # Retain singleton-aware domain deltas; only recompute the private routine rows.
        deltas = tuple(delta for delta in result.deltas if delta.projection != "tabletop.routines")
        return result.model_copy(
            update={"deltas": (*deltas, *projection_deltas(state, working, ("tabletop.routines",)))}
        )

    return execute

"""Branch-clock action costs; models choose attempts, never duration or readiness."""

from __future__ import annotations

import uuid

from kernel.command_bus import CommandHandler
from kernel.contracts import CommandProposal, CommandResult, StateDelta
from kernel.errors import BodyActionPending
from kernel.state import BranchState

ACTION_TIME = "tabletop.action_time"
ACTION_TIME_VERSION = "tabletop-action-time-1.0.0"
ROUND_SECONDS = 6
UNTIMED_COMMANDS = frozenset(
    {
        "tabletop.dialogue.speak",
        "tabletop.console.submit",
        "tabletop.quest.advance",
        "tabletop.rest.start",
    }
)


def wait_seconds(state: BranchState, entity_id: uuid.UUID, *, at_seconds: int | None = None) -> int:
    clock = state.projections.get("tabletop.clock", {}).get("singleton")
    if clock is None:
        return 0
    row = state.projections.get(ACTION_TIME, {}).get(str(entity_id), {})
    now = int(clock["seconds"]) if at_seconds is None else at_seconds
    return max(0, int(row.get("ready_seconds", 0)) - now)


def duration_seconds(command_type: str, body: dict) -> int:
    if command_type == "tabletop.spatial.move":
        speed = int(body.get("speed", 30))
        if speed <= 0:
            raise ValueError("body cannot move at its current speed")
        # One grid step is five feet; round upward at the clock's integer-second resolution.
        return max(1, (5 * ROUND_SECONDS + speed - 1) // speed)
    return ROUND_SECONDS


def with_action_time(handler: CommandHandler) -> CommandHandler:
    def execute(proposal: CommandProposal, state: BranchState) -> CommandResult:
        clock = state.projections.get("tabletop.clock", {}).get("singleton")
        if clock is None or proposal.command_type in UNTIMED_COMMANDS:
            return handler(proposal, state)
        if str(clock["run_id"]) != str(proposal.run_id):
            raise ValueError("action requires the current run's clock")
        entity_id = proposal.embodied_entity_id
        if entity_id is None:
            raise ValueError("timed actions require an embodied entity")
        if wait_seconds(state, entity_id):
            raise BodyActionPending("body is still completing its previous action")
        body = state.projections.get("tabletop.entities", {}).get(str(entity_id), {})
        duration = duration_seconds(proposal.command_type, body)
        result = handler(proposal, state)
        if not result.accepted:
            return result
        now = int(clock["seconds"])
        ready = now + duration
        record = {
            "rules_version": ACTION_TIME_VERSION,
            "run_id": str(proposal.run_id),
            "command_type": proposal.command_type,
            "started_seconds": now,
            "duration_seconds": duration,
            "ready_seconds": ready,
        }
        if proposal.command_type == "tabletop.combat.guard":
            record["guard_expires_seconds"] = ready
        return result.model_copy(
            update={
                "deltas": (
                    *result.deltas,
                    StateDelta(
                        projection=ACTION_TIME,
                        operation="SET",
                        entity_id=entity_id,
                        values=record,
                    ),
                )
            }
        )

    return execute


def expire_guards(state: BranchState, until_seconds: int) -> None:
    """Only mutate the clock handler's isolated working state, then emit ordinary deltas."""
    bodies = state.projections.get("tabletop.entities", {})
    for identity, row in sorted(state.projections.get(ACTION_TIME, {}).items()):
        expiry = row.get("guard_expires_seconds")
        body = bodies.get(identity)
        if expiry is not None and int(expiry) <= until_seconds and body and body.get("guarded"):
            body["guarded"] = False

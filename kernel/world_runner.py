"""World-time driver. Every tick is a normal typed, authorized, atomic kernel command."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from domains.tabletop.world_time import read_clock
from kernel.application import SimulationApplication
from kernel.contracts import BranchKind, CommandProposal, RunKind
from kernel.due_work import ClockLeaseLost, PostgresDueWork
from kernel.errors import KernelError


class WorldRunner:
    def __init__(
        self, snapshot: Callable[[], SimulationApplication], queue: PostgresDueWork | None = None
    ) -> None:
        self.snapshot = snapshot
        self.queue = queue

    def run_once(self, now: datetime | None = None) -> int:
        boundary = now or datetime.now(UTC)
        if boundary.tzinfo is None:
            raise ValueError("world runner requires timezone-aware operational time")
        source = self.snapshot()
        submitted = 0
        due = [
            (clock.next_due, str(state.branch_id), state, clock)
            for state in source.states.all()
            if state.kind is BranchKind.CANONICAL
            and (clock := read_clock(state)) is not None
            and not clock.paused
            and clock.next_due <= boundary
        ]
        for _, _, state, clock in sorted(due, key=lambda entry: entry[:2]):
            run = source.runs.get(clock.run_id)
            if run is None or run.kind != RunKind.LIVE or run.status not in {"ACTIVE", "RUNNING"}:
                continue
            token = (
                self.queue.claim(state.world_id, state.branch_id, clock, boundary)
                if self.queue
                else None
            )
            if self.queue is not None and token is None:
                continue
            proposal = CommandProposal(
                world_id=state.world_id,
                branch_id=state.branch_id,
                run_id=clock.run_id,
                actor_id=clock.executor_actor_id,
                command_type="tabletop.clock.tick",
                idempotency_key=f"world-clock:{state.branch_id}:{clock.epoch}:{clock.step}",
                input_origin="OPERATOR",
                parameters={
                    "epoch": clock.epoch,
                    "step": clock.step,
                    "wall_time": boundary.isoformat(),
                    "lease_token": str(token) if token else None,
                },
            )
            try:
                source.submit(proposal)
                submitted += 1
            except ClockLeaseLost:
                continue
            except (ValueError, PermissionError, KernelError):
                if self.queue is not None and token is not None:
                    self.queue.retry(proposal, token)
        return submitted

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(0.25)

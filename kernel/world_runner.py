"""World-time driver. Every tick is a normal typed, authorized, atomic kernel command."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from domains.tabletop.world_time import read_clock
from kernel.application import SimulationApplication
from kernel.contracts import BranchKind, CommandProposal, RunKind
from kernel.errors import KernelError


class WorldRunner:
    def __init__(self, snapshot: Callable[[], SimulationApplication]) -> None:
        self.snapshot = snapshot

    def run_once(self, now: datetime | None = None) -> int:
        boundary = now or datetime.now(UTC)
        if boundary.tzinfo is None:
            raise ValueError("world runner requires timezone-aware operational time")
        source = self.snapshot()
        submitted = 0
        for state in source.states.all():
            clock = read_clock(state)
            if (
                state.kind != BranchKind.CANONICAL
                or clock is None
                or clock.paused
                or clock.next_due > boundary
            ):
                continue
            run = source.runs.get(clock.run_id)
            if run is None or run.kind != RunKind.LIVE or run.status not in {"ACTIVE", "RUNNING"}:
                continue
            try:
                source.submit(
                    CommandProposal(
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
                        },
                    )
                )
                submitted += 1
            except (ValueError, PermissionError, KernelError):
                # A competing worker, pause/reassignment or revoked authority may win.
                # No raw diagnostics or private operational payloads enter character fiction.
                continue
        return submitted

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(0.25)

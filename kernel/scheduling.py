from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import UTC, datetime

from kernel.contracts import CommandProposal


@dataclass(order=True, frozen=True)
class ScheduledCommand:
    due_at: datetime
    order: int
    proposal: CommandProposal = field(compare=False)


class DeterministicScheduler:
    """A persistence-agnostic priority queue with stable same-time ordering."""

    def __init__(self) -> None:
        self._queue: list[ScheduledCommand] = []
        self._counter = 0

    def schedule(self, due_at: datetime, proposal: CommandProposal) -> None:
        if due_at.tzinfo is None:
            raise ValueError("scheduled times must be timezone-aware")
        self._counter += 1
        heapq.heappush(
            self._queue,
            ScheduledCommand(due_at.astimezone(UTC), self._counter, proposal),
        )

    def due(self, now: datetime) -> tuple[CommandProposal, ...]:
        if now.tzinfo is None:
            raise ValueError("scheduler clock must be timezone-aware")
        values: list[CommandProposal] = []
        boundary = now.astimezone(UTC)
        while self._queue and self._queue[0].due_at <= boundary:
            values.append(heapq.heappop(self._queue).proposal)
        return tuple(values)

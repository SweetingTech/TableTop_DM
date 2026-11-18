from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from kernel.application import SimulationApplication, stable_id
from kernel.contracts import ActorKind
from kernel.control import (
    MAX_DISCONNECT_SECONDS,
    MIN_DISCONNECT_SECONDS,
    ControllerState,
    ControlMode,
    ControlScope,
)

EXECUTOR_CAPABILITIES = frozenset({"world.read", "action.propose", "action.commit", "entity.act"})
REPLAN_LIMIT = 3


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    expected_epoch: int = Field(ge=0)
    mode: ControlMode
    idempotency_key: str = Field(min_length=1, max_length=200)
    max_steps: int = Field(default=20, ge=1, le=1000)
    interval_ms: int = Field(default=1000, ge=100, le=60000)
    disconnect_after_seconds: int | None = Field(
        default=None, ge=MIN_DISCONNECT_SECONDS, le=MAX_DISCONNECT_SECONDS
    )


class PresenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    expected_epoch: int = Field(ge=1)


class HandoffReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: uuid.UUID
    idempotency_key: str
    state: ControllerState
    sensory_event: bool = False
    recap_revision: int | None = Field(default=None, ge=0, exclude_if=lambda v: v is None)


@dataclass(frozen=True)
class RecapWindow:
    after_revision: int
    through_revision: int


def recap_bounds(
    start: HandoffReceipt,
    end: HandoffReceipt | None,
    current: ControllerState,
    current_revision: int,
) -> RecapWindow | None:
    if (end is None and current.epoch != start.state.epoch) or (
        end is not None and end.state.epoch != start.state.epoch + 1
    ):
        return None
    after = start.recap_revision
    through = end.recap_revision if end is not None else current_revision
    if after is None or through is None or through < after:
        return None
    return RecapWindow(after, through)


class ControlConflict(ValueError):
    pass


def execution_actor(scope: ControlScope) -> uuid.UUID:
    return stable_id("character-executor:" + ":".join(map(str, scope.key)))


def next_controller(
    scope: ControlScope,
    actor_id: uuid.UUID,
    owner: uuid.UUID,
    request: HandoffRequest,
    previous: ControllerState | None,
    *,
    disconnected: bool = False,
    presence_now: datetime | None = None,
) -> ControllerState:
    epoch = previous.epoch if previous else 0
    if request.expected_epoch != epoch:
        raise ControlConflict("controller changed; reload before handing off")
    timeout = previous.disconnect_after_seconds if previous else None
    if "disconnect_after_seconds" in request.model_fields_set:
        if actor_id != owner or request.mode != "HUMAN":
            raise PermissionError("only the human controller can configure disconnect handling")
        timeout = request.disconnect_after_seconds
    return ControllerState(
        **scope.model_dump(),
        owner_actor_id=owner,
        executor_actor_id=execution_actor(scope),
        epoch=epoch + 1,
        mode=request.mode,
        max_steps=previous.max_steps
        if request.mode == "PAUSED" and previous
        else request.max_steps,
        interval_ms=previous.interval_ms
        if request.mode == "PAUSED" and previous
        else request.interval_ms,
        step=previous.step if request.mode == "PAUSED" and previous else 0,
        disconnect_after_seconds=timeout,
        presence_deadline_at=(presence_now or datetime.now(UTC)) + timedelta(seconds=timeout)
        if timeout is not None and request.mode == "HUMAN"
        else None,
        handoff_reason="DISCONNECT_TIMEOUT" if disconnected else None,
    )


class ControllerRepository(Protocol):
    def get(self, scope: ControlScope, actor_id: uuid.UUID) -> ControllerState | None: ...
    def handoff(
        self, scope: ControlScope, actor_id: uuid.UUID, request: HandoffRequest
    ) -> HandoffReceipt: ...
    def presence(
        self, scope: ControlScope, actor_id: uuid.UUID, expected_epoch: int
    ) -> ControllerState: ...
    def recap_window(self, scope: ControlScope, actor_id: uuid.UUID) -> RecapWindow | None: ...
    def due(self) -> tuple[ControllerState, ...]: ...
    def defer(self, state: ControllerState, code: str | None, *, retry_limit: int = 0) -> None: ...


def renew_presence(
    state: ControllerState | None, expected_epoch: int, *, now: datetime | None = None
) -> ControllerState:
    if (
        state is None
        or state.epoch != expected_epoch
        or state.mode != "HUMAN"
        or state.disconnect_after_seconds is None
    ):
        raise ControlConflict("controller changed; reload before renewing presence")
    deadline = (now or datetime.now(UTC)) + timedelta(seconds=state.disconnect_after_seconds)
    if state.presence_deadline_at is not None and deadline <= state.presence_deadline_at:
        return state
    return state.model_copy(update={"presence_deadline_at": deadline})


def disconnect_due(state: ControllerState, now: datetime) -> bool:
    return bool(
        state.mode == "HUMAN"
        and state.disconnect_after_seconds is not None
        and state.presence_deadline_at is not None
        and state.presence_deadline_at <= now
    )


def disconnect_handoff(state: ControllerState) -> HandoffRequest:
    return HandoffRequest(
        run_id=state.run_id,
        expected_epoch=state.epoch,
        mode="AUTONOMOUS",
        idempotency_key=f"presence-timeout:{state.epoch}",
        max_steps=state.max_steps,
        interval_ms=state.interval_ms,
    )


def deferred_controller(
    state: ControllerState, code: str | None, *, retry_limit: int
) -> ControllerState:
    """Reschedule a poll and record a policy failure only when one is supplied."""
    next_due = datetime.now(UTC) + timedelta(milliseconds=250)
    if code is None:
        return state.model_copy(update={"next_due": next_due})
    failures = state.failures + 1
    return state.model_copy(
        update={
            "mode": "AUTONOMOUS" if failures <= retry_limit else "PAUSED",
            "last_error": code,
            "failures": failures,
            "next_due": next_due,
        }
    )


class InMemoryControllers:
    def __init__(
        self,
        simulation: SimulationApplication,
        binding_exists: Callable[[ControlScope, uuid.UUID], bool],
        on_handoff: Callable[[ControllerState], None] | None = None,
        *,
        machine_actor_id: uuid.UUID,
    ) -> None:
        self.simulation = simulation
        self.binding_exists = binding_exists
        self.on_handoff = on_handoff
        self.machine_actor_id = machine_actor_id
        self.rows = simulation.controller_states
        self.receipts: dict[tuple, HandoffReceipt] = {}
        self._lock = threading.RLock()

    def _owner(self, scope: ControlScope, actor_id: uuid.UUID) -> uuid.UUID:
        simulation = self.simulation
        run = simulation.runs.get(scope.run_id)
        entity = simulation.entities.get((scope.branch_id, scope.entity_id))
        if (
            run is None
            or (run.world_id, run.branch_id) != (scope.world_id, scope.branch_id)
            or (entity is None or entity.world_id != scope.world_id)
        ):
            raise ValueError("controller scope is unavailable")
        actor = simulation.authority(scope.world_id, actor_id)
        owner = entity.controller_actor_id
        if actor_id != owner and "mind.write.all" not in actor.capabilities:
            raise PermissionError("actor cannot manage this controller")
        return owner or actor_id

    def get(self, scope: ControlScope, actor_id: uuid.UUID) -> ControllerState | None:
        self._owner(scope, actor_id)
        return self.rows.get(scope.key)

    def handoff(
        self, scope: ControlScope, actor_id: uuid.UUID, request: HandoffRequest
    ) -> HandoffReceipt:
        return self._handoff(scope, actor_id, request)

    def _check_player(self, scope: ControlScope, actor_id: uuid.UUID) -> None:
        entity = self.simulation.entities[(scope.branch_id, scope.entity_id)]
        actor = self.simulation.authority(scope.world_id, actor_id)
        if (
            entity.controller_actor_id != actor_id
            or entity.entity_type != "PLAYER_CHARACTER"
            or actor.kind is not ActorKind.HUMAN
            or not actor.has_capabilities(EXECUTOR_CAPABILITIES)
        ):
            raise PermissionError("controller presence requires the current human player")

    def _handoff(
        self,
        scope: ControlScope,
        actor_id: uuid.UUID,
        request: HandoffRequest,
        *,
        timeout_at: datetime | None = None,
    ) -> HandoffReceipt:
        def transition():
            with self._lock:
                owner = self._owner(scope, actor_id)
                if not self.simulation.authority(scope.world_id, actor_id).has_capabilities(
                    EXECUTOR_CAPABILITIES
                    if request.mode == "AUTONOMOUS"
                    else frozenset({"action.propose", "action.commit"})
                ):
                    raise PermissionError("actor lacks controller execution capabilities")
                if self.simulation.runs[scope.run_id].kind.value != "LIVE" or (
                    self.simulation.states.get(scope.branch_id).kind.value != "CANONICAL"
                ):
                    raise ValueError("controllers require a canonical live run")
                key = (*scope.key, actor_id, request.idempotency_key)
                if key in self.receipts:
                    return self.receipts[key]
                previous = self.rows.get(scope.key)
                if "disconnect_after_seconds" in request.model_fields_set:
                    self._check_player(scope, actor_id)
                if timeout_at is not None:
                    self._check_player(scope, owner)
                    if (
                        previous is None
                        or previous.owner_actor_id != owner
                        or not disconnect_due(previous, timeout_at)
                        or self.simulation.runs[scope.run_id].status not in {"ACTIVE", "RUNNING"}
                    ):
                        raise ControlConflict("controller presence changed")
                if (
                    request.mode == "AUTONOMOUS" or request.disconnect_after_seconds is not None
                ) and not self.binding_exists(scope, actor_id):
                    raise ValueError(
                        "a pinned CHARACTER binding is required before autonomous play"
                    )
                state = next_controller(
                    scope, actor_id, owner, request, previous, disconnected=timeout_at is not None
                )
                if state.executor_actor_id not in self.simulation.actors:
                    self.simulation.create_actor(
                        "Character policy executor",
                        ActorKind.AGENT,
                        set(),
                        set(EXECUTOR_CAPABILITIES),
                        set(),
                        world_id=scope.world_id,
                        actor_id=state.executor_actor_id,
                    )
                if self.on_handoff is not None:
                    self.on_handoff(state)
                self.rows[scope.key] = state
                self.simulation.controller_states[scope.key] = state
                receipt = HandoffReceipt(
                    actor_id=actor_id,
                    idempotency_key=request.idempotency_key,
                    state=state,
                    recap_revision=self.simulation.states.get(scope.branch_id).version,
                )
                self.receipts[key] = receipt
                return receipt

        return self.simulation.read_reference(transition)

    def recap_window(self, scope: ControlScope, actor_id: uuid.UUID) -> RecapWindow | None:
        def read() -> RecapWindow | None:
            self._owner(scope, actor_id)
            current = self.rows.get(scope.key)
            rows = sorted(
                (row for row in self.receipts.values() if row.state.key == scope.key),
                key=lambda row: row.state.epoch,
            )
            if current is None or not any(row.state.mode == "AUTONOMOUS" for row in rows):
                return None
            index = max(i for i, row in enumerate(rows) if row.state.mode == "AUTONOMOUS")
            end = rows[index + 1] if index + 1 < len(rows) else None
            return recap_bounds(
                rows[index], end, current, self.simulation.states.get(scope.branch_id).version
            )

        return self.simulation.read_reference(read)

    def presence(
        self, scope: ControlScope, actor_id: uuid.UUID, expected_epoch: int
    ) -> ControllerState:
        def transition():
            self._owner(scope, actor_id)
            self._check_player(scope, actor_id)
            state = renew_presence(self.rows.get(scope.key), expected_epoch)
            self.rows[scope.key] = state
            return state

        return self.simulation.read_reference(transition)

    def expire_disconnected(self, now: datetime) -> None:
        for state in tuple(self.rows.values()):
            if disconnect_due(state, now):
                try:
                    self._handoff(
                        state.scope,
                        self.machine_actor_id,
                        disconnect_handoff(state),
                        timeout_at=now,
                    )
                except (ControlConflict, PermissionError, ValueError):
                    continue

    def due(self) -> tuple[ControllerState, ...]:
        self.expire_disconnected(datetime.now(UTC))
        return tuple(
            row
            for _, row in sorted(self.rows.items(), key=lambda pair: str(pair[0]))
            if row.mode == "AUTONOMOUS"
            and row.next_due <= datetime.now(UTC)
            and self.simulation.runs[row.run_id].status in {"ACTIVE", "RUNNING"}
        )

    def defer(self, state: ControllerState, code: str | None, *, retry_limit: int = 0) -> None:
        def update():
            current = self.rows.get(state.key)
            if current != state or state.mode != "AUTONOMOUS":
                return
            changed = deferred_controller(state, code, retry_limit=retry_limit)
            self.rows[state.key] = changed
            self.simulation.controller_states[state.key] = changed

        self.simulation.read_reference(update)

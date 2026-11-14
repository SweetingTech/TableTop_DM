from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from kernel.application import SimulationApplication, stable_id
from kernel.contracts import ActorKind
from kernel.control import ControllerState, ControlMode, ControlScope

EXECUTOR_CAPABILITIES = frozenset({"world.read", "action.propose", "action.commit", "entity.act"})


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: uuid.UUID
    expected_epoch: int = Field(ge=0)
    mode: ControlMode
    idempotency_key: str = Field(min_length=1, max_length=200)
    max_steps: int = Field(default=20, ge=1, le=1000)
    interval_ms: int = Field(default=1000, ge=100, le=60000)


class HandoffReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)
    actor_id: uuid.UUID
    idempotency_key: str
    state: ControllerState
    sensory_event: bool = False


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
) -> ControllerState:
    epoch = previous.epoch if previous else 0
    if request.expected_epoch != epoch:
        raise ControlConflict("controller changed; reload before handing off")
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
    )


class ControllerRepository(Protocol):
    def get(self, scope: ControlScope, actor_id: uuid.UUID) -> ControllerState | None: ...
    def handoff(
        self, scope: ControlScope, actor_id: uuid.UUID, request: HandoffRequest
    ) -> HandoffReceipt: ...
    def due(self) -> tuple[ControllerState, ...]: ...
    def defer(self, state: ControllerState, code: str, *, pending: bool = False) -> None: ...


class InMemoryControllers:
    def __init__(
        self,
        simulation: SimulationApplication,
        binding_exists: Callable[[ControlScope, uuid.UUID], bool],
        on_handoff: Callable[[ControllerState], None] | None = None,
    ) -> None:
        self.simulation = simulation
        self.binding_exists = binding_exists
        self.on_handoff = on_handoff
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
                if request.mode == "AUTONOMOUS" and not self.binding_exists(scope, actor_id):
                    raise ValueError(
                        "a pinned CHARACTER binding is required before autonomous play"
                    )
                state = next_controller(scope, actor_id, owner, request, self.rows.get(scope.key))
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
                    actor_id=actor_id, idempotency_key=request.idempotency_key, state=state
                )
                self.receipts[key] = receipt
                return receipt

        return self.simulation.read_reference(transition)

    def due(self) -> tuple[ControllerState, ...]:
        return tuple(
            row
            for _, row in sorted(self.rows.items(), key=lambda pair: str(pair[0]))
            if row.mode == "AUTONOMOUS"
            and row.next_due <= datetime.now(UTC)
            and self.simulation.runs[row.run_id].status in {"ACTIVE", "RUNNING"}
        )

    def defer(self, state: ControllerState, code: str, *, pending: bool = False) -> None:
        def update():
            current = self.rows.get(state.key)
            if current is None or (current.epoch, current.step, current.mode) != (
                state.epoch,
                state.step,
                "AUTONOMOUS",
            ):
                return
            failures = current.failures + 1
            changed = current.model_copy(
                update={
                    "mode": "AUTONOMOUS" if pending and failures < 40 else "PAUSED",
                    "last_error": code,
                    "failures": failures,
                    "next_due": datetime.now(UTC) + timedelta(milliseconds=250),
                }
            )
            self.rows[state.key] = changed
            self.simulation.controller_states[state.key] = changed

        self.simulation.read_reference(update)

"""Operational controller contracts; these records never enter sensory events."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from kernel.contracts import CommandProposal
from kernel.errors import AuthorizationDenied

ControlMode = Literal["HUMAN", "AUTONOMOUS", "PAUSED"]


class ControlScope(BaseModel):
    model_config = ConfigDict(frozen=True)
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID

    @property
    def key(self) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
        return self.world_id, self.branch_id, self.run_id, self.entity_id


class ControllerState(ControlScope):
    owner_actor_id: uuid.UUID
    executor_actor_id: uuid.UUID
    epoch: int = Field(ge=1)
    mode: ControlMode
    step: int = Field(default=0, ge=0)
    max_steps: int = Field(default=20, ge=1, le=1000)
    interval_ms: int = Field(default=1000, ge=100, le=60000)
    next_due: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    failures: int = Field(default=0, ge=0)
    last_error: str | None = None

    @property
    def scope(self) -> ControlScope:
        return ControlScope.model_validate(self.model_dump())


def validate_controller(proposal: CommandProposal, state: ControllerState | None) -> None:
    if state is None:
        if (
            proposal.control_epoch is not None
            or proposal.control_step is not None
            or proposal.decision_authorship != "HUMAN"
        ):
            raise AuthorizationDenied("controller assignment is unavailable")
        return
    if proposal.control_epoch != state.epoch:
        raise AuthorizationDenied("controller changed; reload before acting")
    if state.mode == "HUMAN":
        allowed = (
            proposal.actor_id == state.owner_actor_id
            and proposal.decision_authorship == "HUMAN"
            and proposal.control_step is None
        )
    else:
        allowed = (
            state.mode == "AUTONOMOUS"
            and proposal.actor_id == state.executor_actor_id
            and proposal.decision_authorship == "CHARACTER_POLICY"
            and proposal.control_step == state.step
            and state.step < state.max_steps
            and state.next_due <= datetime.now(UTC)
            and proposal.decision_trace_id is not None
        )
    if not allowed:
        raise AuthorizationDenied("this controller cannot act; take control or resume explicitly")


def advanced(state: ControllerState) -> ControllerState:
    step = state.step + 1
    return state.model_copy(
        update={
            "step": step,
            "mode": "PAUSED" if step >= state.max_steps else "AUTONOMOUS",
            "last_error": "step_limit" if step >= state.max_steps else None,
            "failures": 0,
            "next_due": datetime.now(UTC) + timedelta(milliseconds=state.interval_ms),
        }
    )


def load_controller(cursor: Any, proposal: CommandProposal) -> ControllerState | None:
    if proposal.embodied_entity_id is None:
        return None
    cursor.execute(
        "SELECT payload FROM cognition.controller_assignments "
        "WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s)",
        tuple(
            map(
                str,
                (
                    proposal.world_id,
                    proposal.branch_id,
                    proposal.run_id,
                    proposal.embodied_entity_id,
                ),
            )
        ),
    )
    row = cursor.fetchone()
    return ControllerState.model_validate(row["payload"]) if row else None


def persist_controller(cursor: Any, state: ControllerState) -> None:
    cursor.execute(
        "UPDATE cognition.controller_assignments SET payload=%s::jsonb "
        "WHERE (world_id,branch_id,run_id,entity_id)=(%s,%s,%s,%s)",
        (state.model_dump_json(), *map(str, state.key)),
    )

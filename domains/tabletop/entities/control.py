"""Authorized roster control changes; these are operational, never sensory evidence."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kernel.command_bus import CommandDefinition
from kernel.contracts import (
    BranchKind,
    CommandProposal,
    CommandResult,
    EntityControllerMutation,
    StateDelta,
)
from kernel.state import BranchState


class ControllerChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entity_id: uuid.UUID
    controller_actor_id: uuid.UUID | None


class SetControllersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: tuple[ControllerChange, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_bodies(self):
        if len({row.entity_id for row in self.changes}) != len(self.changes):
            raise ValueError("a body can only appear once in a control change")
        return self


class SetControllersResult(BaseModel):
    entity_ids: tuple[uuid.UUID, ...]


def set_controllers(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = SetControllersRequest.model_validate(proposal.parameters)
    for change in request.changes:
        if str(change.entity_id) not in state.projections.get("tabletop.entities", {}):
            raise ValueError("controlled body is unavailable in this branch")
    return CommandResult(
        result={"entity_ids": [str(row.entity_id) for row in request.changes]},
        deltas=tuple(
            StateDelta(
                projection="tabletop.sensory_profiles",
                operation="MERGE",
                entity_id=row.entity_id,
                values={
                    "controller_actor_id": str(row.controller_actor_id)
                    if row.controller_actor_id
                    else None
                },
            )
            for row in request.changes
        ),
        controller_mutations=tuple(
            EntityControllerMutation(**row.model_dump()) for row in request.changes
        ),
        domain_tags=("tabletop", "entity", "controller"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.entity.set_controllers",
        required_capabilities=frozenset({"entity.control", "mind.write.all"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        handler=set_controllers,
        request_model=SetControllersRequest,
        result_model=SetControllersResult,
        sensitive_parameters=frozenset({"changes"}),
    )

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from domains.tabletop.rules import dead
from domains.tabletop.spatial.models import SpatialPosition
from kernel.checkpoint_holds import CheckpointHoldConflict
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.errors import AuthorizationDenied
from kernel.state import BranchState

CORRECT = "tabletop.timeline.correct"
ENTITIES = "tabletop.entities"
POSITIONS = "tabletop.spatial.positions"


class HitPointCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact: Literal["HIT_POINTS"]
    entity_id: uuid.UUID
    hit_points: int = Field(strict=True, ge=1)


class PositionCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fact: Literal["POSITION"]
    entity_id: uuid.UUID
    x: int = Field(strict=True, ge=-(2**31), le=2**31 - 1)
    y: int = Field(strict=True, ge=-(2**31), le=2**31 - 1)


Correction = Annotated[HitPointCorrection | PositionCorrection, Field(discriminator="fact")]
CorrectionBatch = Annotated[tuple[Correction, ...], Field(min_length=1, max_length=16)]


class CorrectTimelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_epoch: int = Field(strict=True, ge=1, le=2**63 - 1)
    expected_state_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ] = Field(repr=False)
    corrections: CorrectionBatch

    @model_validator(mode="after")
    def distinct_facts(self) -> CorrectTimelineRequest:
        if len({(patch.entity_id, patch.fact) for patch in self.corrections}) != len(
            self.corrections
        ):
            raise ValueError("a correction can change each selected fact only once")
        return self


class CorrectTimelineResult(BaseModel):
    epoch: int
    corrected_facts: int


def position_deltas(
    state: BranchState, body: dict, patch: PositionCorrection
) -> tuple[StateDelta, StateDelta]:
    current = state.projections.get(POSITIONS, {}).get(str(patch.entity_id), body)
    zone_id = current.get("zone_id", "world")
    destination = (patch.x, patch.y)
    obstacles = state.projections.get("tabletop.obstacles", {}).values()
    occluders = state.projections.get("tabletop.spatial.occluders", {}).values()
    if any((row["x"], row["y"]) == destination for row in obstacles) or any(
        row.get("zone_id", "world") == zone_id
        and row.get("blocks_movement", True)
        and (row["x"], row["y"]) == destination
        for row in occluders
    ):
        raise ValueError("corrected position is blocked")
    position = SpatialPosition(
        entity_id=patch.entity_id,
        zone_id=zone_id,
        x=patch.x,
        y=patch.y,
        z=current.get("z", 0),
        facing=current.get("facing"),
    )
    return (
        StateDelta(
            projection=POSITIONS,
            operation="SET",
            entity_id=patch.entity_id,
            values=position.model_dump(mode="json", exclude={"entity_id"}),
        ),
        StateDelta(
            projection=ENTITIES,
            operation="MERGE",
            entity_id=patch.entity_id,
            values={"x": patch.x, "y": patch.y},
        ),
    )


def correct_timeline(proposal: CommandProposal, state: BranchState) -> CommandResult:
    if proposal.input_origin != "OPERATOR" or proposal.embodied_entity_id is not None:
        raise AuthorizationDenied("a timeline correction requires operator authority")
    request = CorrectTimelineRequest.model_validate(proposal.parameters)
    return resolve_correction(state, request)


def resolve_correction(state: BranchState, request: CorrectTimelineRequest) -> CommandResult:
    if request.expected_state_hash != state.state_hash:
        raise CheckpointHoldConflict("the paused revision state changed before correction")
    deltas: list[StateDelta] = []
    for patch in request.corrections:
        body = state.projections.get(ENTITIES, {}).get(str(patch.entity_id))
        if body is None:
            raise ValueError("corrected body is unavailable in this branch")
        if isinstance(patch, PositionCorrection):
            deltas.extend(position_deltas(state, body, patch))
            continue
        if dead(body) or int(body.get("hp", 0)) < 1 or body.get("defeated"):
            raise ValueError("hit point correction requires a living, undefeated body")
        if patch.hit_points > int(body.get("max_hp", 0)):
            raise ValueError("corrected hit points exceed the body's maximum")
        deltas.append(
            StateDelta(
                projection=ENTITIES,
                operation="MERGE",
                entity_id=patch.entity_id,
                values={"hp": patch.hit_points},
            )
        )
    return CommandResult(
        result=CorrectTimelineResult(
            epoch=request.expected_epoch, corrected_facts=len(request.corrections)
        ).model_dump(mode="json"),
        deltas=tuple(deltas),
        domain_tags=("operator", "timeline_revision"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type=CORRECT,
        required_capabilities=frozenset(
            {"action.propose", "world.read.all", "entity.control", "run.branch"}
        ),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
        requires_durable_scope=True,
        handler=correct_timeline,
        request_model=CorrectTimelineRequest,
        result_model=CorrectTimelineResult,
    )

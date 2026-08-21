from __future__ import annotations

import uuid
from typing import Any

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

from .models import (
    CameraMode,
    ControlAuthorityMode,
    SetControlModeRequest,
    SetControlModeResult,
    SquadOrderRequest,
    SquadOrderResult,
)


def _embodied_entity(
    proposal: CommandProposal, state: BranchState
) -> tuple[uuid.UUID, str, dict[str, Any]]:
    entity_id = proposal.embodied_entity_id
    if entity_id is None:
        raise ValueError("battlefield control requires an embodied entity")
    key = str(entity_id)
    entity = state.projections.get("tabletop.entities", {}).get(key)
    if entity is None:
        raise ValueError("embodied entity does not exist")
    return entity_id, key, entity


def set_control_mode(proposal: CommandProposal, state: BranchState) -> CommandResult:
    entity_id, entity_key, _entity = _embodied_entity(proposal, state)
    request = SetControlModeRequest.model_validate(proposal.parameters)
    existing = state.projections.get("tabletop.control_modes", {}).get(entity_key, {})
    previous = CameraMode(existing.get("camera_mode", CameraMode.TACTICAL))
    control_authority = (
        ControlAuthorityMode.FORMATION
        if request.camera_mode is CameraMode.TACTICAL
        else ControlAuthorityMode.DIRECT
    )
    revision = int(existing.get("revision", 0)) + 1
    values = {
        "camera_mode": request.camera_mode.value,
        "control_authority": control_authority.value,
        # Followers remain autonomous in every camera/control mode.
        "squad_ai": "ACTIVE",
        "revision": revision,
    }
    return CommandResult(
        result=SetControlModeResult(
            entity_id=entity_id,
            previous_camera_mode=previous,
            camera_mode=request.camera_mode,
            control_authority=control_authority,
            squad_ai="ACTIVE",
            revision=revision,
        ).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.control_modes",
                operation="MERGE",
                entity_id=entity_id,
                values=values,
            ),
        ),
        domain_tags=("tabletop", "battlefield", "control-mode"),
    )


def issue_squad_order(proposal: CommandProposal, state: BranchState) -> CommandResult:
    leader_id, leader_key, _leader = _embodied_entity(proposal, state)
    request = SquadOrderRequest.model_validate(proposal.parameters)
    squad_key = str(request.squad_id)
    squad = state.projections.get("tabletop.squads", {}).get(squad_key)
    if squad is None:
        raise ValueError("squad does not exist")
    if str(squad.get("leader_entity_id")) != leader_key:
        raise ValueError("embodied entity is not the squad leader")
    if request.target_entity_id is not None and str(
        request.target_entity_id
    ) not in state.projections.get("tabletop.entities", {}):
        raise ValueError("squad-order target does not exist")

    existing = state.projections.get("tabletop.squad_orders", {}).get(squad_key, {})
    revision = int(existing.get("revision", 0)) + 1
    values = {
        "order": request.order.value,
        "leader_entity_id": leader_key,
        "target_entity_id": (
            str(request.target_entity_id) if request.target_entity_id is not None else None
        ),
        "focus_point": (
            request.focus_point.model_dump(mode="json") if request.focus_point is not None else None
        ),
        "squad_ai": "ACTIVE",
        "revision": revision,
    }
    return CommandResult(
        result=SquadOrderResult(
            squad_id=request.squad_id,
            leader_entity_id=leader_id,
            order=request.order,
            target_entity_id=request.target_entity_id,
            focus_point=request.focus_point,
            squad_ai="ACTIVE",
            revision=revision,
        ).model_dump(mode="json"),
        deltas=(
            StateDelta(
                projection="tabletop.squad_orders",
                operation="MERGE",
                entity_id=request.squad_id,
                values=values,
            ),
        ),
        domain_tags=("tabletop", "battlefield", "squad-order"),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    required = frozenset({"action.propose", "entity.act"})
    branches = frozenset({BranchKind.CANONICAL, BranchKind.TRIAL})
    return (
        CommandDefinition(
            command_type="tabletop.battlefield.set_control_mode",
            required_capabilities=required,
            allowed_branch_kinds=branches,
            handler=set_control_mode,
            request_model=SetControlModeRequest,
            result_model=SetControlModeResult,
            requires_controlled_entity=True,
        ),
        CommandDefinition(
            command_type="tabletop.battlefield.issue_squad_order",
            required_capabilities=required,
            allowed_branch_kinds=branches,
            handler=issue_squad_order,
            request_model=SquadOrderRequest,
            result_model=SquadOrderResult,
            requires_controlled_entity=True,
        ),
    )

from __future__ import annotations

import copy
import uuid
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from kernel.state import BranchState

from .models import (
    BattlefieldControlInput,
    CameraMode,
    ControlAuthorityMode,
    ResolvedWeaponStats,
    WeaponDefinition,
    WeaponModifiers,
)


class BattlefieldEntityView(BaseModel):
    model_config = ConfigDict(frozen=True)

    entity_id: uuid.UUID
    entity_type: str
    public_state: dict[str, object]


class BattlefieldSquadView(BaseModel):
    model_config = ConfigDict(frozen=True)

    squad_id: uuid.UUID
    leader_entity_id: uuid.UUID
    member_entity_ids: tuple[uuid.UUID, ...]
    formation: str
    current_order: str
    squad_ai: str


class BattlefieldFrame(BaseModel):
    """Authorized presentation snapshot; never an alternate simulation state."""

    model_config = ConfigDict(frozen=True)

    contract_version: str = "battlefield-frame-1.0.0"
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    projection_version: int
    state_hash: str
    commander_entity_id: uuid.UUID
    camera_mode: CameraMode
    control_authority: ControlAuthorityMode
    squad_ai: str
    commander: BattlefieldEntityView
    squad: BattlefieldSquadView | None = None
    visible_entities: tuple[BattlefieldEntityView, ...] = ()
    weapon: ResolvedWeaponStats | None = None


class BattlefieldRendererPort(Protocol):
    """Hook implemented later by a browser, Unreal, Unity, or another renderer."""

    def present(self, frame: BattlefieldFrame) -> None: ...


class BattlefieldInputPort(Protocol):
    """Hook for engine input; adapters translate this into typed command proposals."""

    def poll(self) -> tuple[BattlefieldControlInput, ...]: ...


class BattlefieldFrameBuilder:
    VERSION = "battlefield-frame-builder-1.0.0"

    @staticmethod
    def build(
        state: BranchState,
        *,
        run_id: uuid.UUID,
        commander_entity_id: uuid.UUID,
        visible_entity_ids: frozenset[uuid.UUID],
    ) -> BattlefieldFrame:
        """Build a view only from entity IDs authorized by perception/visibility policy."""
        entities = state.projections.get("tabletop.entities", {})
        commander_key = str(commander_entity_id)
        commander_state = entities.get(commander_key)
        if commander_state is None:
            raise ValueError("commander entity does not exist")

        def view(entity_id: uuid.UUID, payload: dict[str, Any]) -> BattlefieldEntityView:
            public = copy.deepcopy(payload)
            entity_type = str(public.pop("entity_type", "UNKNOWN"))
            return BattlefieldEntityView(
                entity_id=entity_id,
                entity_type=entity_type,
                public_state=public,
            )

        commander = view(commander_entity_id, commander_state)
        visible = tuple(
            view(entity_id, entities[str(entity_id)])
            for entity_id in sorted(visible_entity_ids - {commander_entity_id}, key=str)
            if str(entity_id) in entities
        )

        control = state.projections.get("tabletop.control_modes", {}).get(commander_key, {})
        camera_mode = CameraMode(control.get("camera_mode", CameraMode.TACTICAL))
        control_authority = ControlAuthorityMode(
            control.get("control_authority", ControlAuthorityMode.FORMATION)
        )
        squad_ai = str(control.get("squad_ai", "ACTIVE"))

        squad_view = None
        for squad_key, squad in sorted(state.projections.get("tabletop.squads", {}).items()):
            if str(squad.get("leader_entity_id")) != commander_key:
                continue
            order = state.projections.get("tabletop.squad_orders", {}).get(squad_key, {})
            squad_view = BattlefieldSquadView(
                squad_id=uuid.UUID(squad_key),
                leader_entity_id=commander_entity_id,
                member_entity_ids=tuple(
                    uuid.UUID(str(value)) for value in squad.get("member_entity_ids", ())
                ),
                formation=str(squad.get("formation", "COLUMN")),
                current_order=str(order.get("order", "FOLLOW")),
                squad_ai=str(order.get("squad_ai", squad_ai)),
            )
            break

        weapon = None
        weapon_id = commander_state.get("weapon_id")
        if weapon_id is not None:
            raw_weapon = state.projections.get("tabletop.weapons", {}).get(str(weapon_id))
            if raw_weapon is not None:
                modifiers = WeaponModifiers.model_validate(
                    commander_state.get("weapon_modifiers", {})
                )
                weapon = ResolvedWeaponStats.resolve(
                    WeaponDefinition.model_validate(raw_weapon), modifiers
                )

        return BattlefieldFrame(
            world_id=state.world_id,
            branch_id=state.branch_id,
            run_id=run_id,
            projection_version=state.version,
            state_hash=state.state_hash,
            commander_entity_id=commander_entity_id,
            camera_mode=camera_mode,
            control_authority=control_authority,
            squad_ai=squad_ai,
            commander=commander,
            squad=squad_view,
            visible_entities=visible,
            weapon=weapon,
        )

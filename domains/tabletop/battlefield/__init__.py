"""Shared-state battlefield control and external-renderer contracts."""

from .bridge import (
    BattlefieldFrame,
    BattlefieldFrameBuilder,
    BattlefieldInputPort,
    BattlefieldRendererPort,
)
from .commands import command_definitions
from .models import (
    BattlefieldControlInput,
    CameraMode,
    ControlAuthorityMode,
    ResolvedWeaponStats,
    SquadOrderKind,
    WeaponDefinition,
    WeaponModifiers,
)

__all__ = [
    "BattlefieldControlInput",
    "BattlefieldFrame",
    "BattlefieldFrameBuilder",
    "BattlefieldInputPort",
    "BattlefieldRendererPort",
    "CameraMode",
    "ControlAuthorityMode",
    "ResolvedWeaponStats",
    "SquadOrderKind",
    "WeaponDefinition",
    "WeaponModifiers",
    "command_definitions",
]

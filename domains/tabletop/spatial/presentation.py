"""World/zone map presentation, separate from physics and character cognition."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domains.tabletop.spatial.scene import PerceivedScene
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState

PROJECTION = "tabletop.map_presentations"


class MapPresentation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    zone_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=160)
    min_x: int = Field(ge=-1_000_000, le=1_000_000)
    max_x: int = Field(ge=-1_000_000, le=1_000_000)
    min_y: int = Field(ge=-1_000_000, le=1_000_000)
    max_y: int = Field(ge=-1_000_000, le=1_000_000)
    image_path: str | None = Field(
        default=None, max_length=512, pattern=r"^/static/[a-zA-Z0-9_./-]+$"
    )

    @model_validator(mode="after")
    def valid_bounds(self) -> Self:
        if self.min_x > self.max_x or self.min_y > self.max_y:
            raise ValueError("map bounds must include at least one grid cell")
        if self.image_path and any(part in {".", ".."} for part in self.image_path.split("/")):
            raise ValueError("map image must be a local static asset")
        return self


class ConfiguredMapResult(BaseModel):
    zone_id: str


def configure_map(proposal: CommandProposal, state: BranchState) -> CommandResult:
    presentation = MapPresentation.model_validate(proposal.parameters)
    existing = state.projections.get(PROJECTION, {}).get("singleton", {})
    if presentation.zone_id not in existing and len(existing) >= 128:
        raise ValueError("this branch already has the maximum number of map presentations")
    return CommandResult(
        result={"zone_id": presentation.zone_id},
        deltas=(
            StateDelta(
                projection=PROJECTION,
                operation="MERGE",
                values={presentation.zone_id: presentation.model_dump(mode="json")},
            ),
        ),
        domain_tags=("tabletop", "presentation", "map"),
    )


def visible_maps(state: BranchState, scene: PerceivedScene) -> tuple[MapPresentation, ...]:
    """Return only configured maps for perceived zones to the human interface."""
    configured = state.projections.get(PROJECTION, {}).get("singleton", {})
    return tuple(
        MapPresentation.model_validate(configured[zone])
        for zone in scene.visible_zones
        if zone in configured
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.map.configure",
        required_capabilities=frozenset({"entity.control", "world.read.all"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=configure_map,
        request_model=MapPresentation,
        result_model=ConfiguredMapResult,
    )

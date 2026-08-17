from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PopulationDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    population_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    size: int = Field(ge=1, le=5_000_000)
    seed: int
    fixed: dict[str, Any] = Field(default_factory=dict)
    distributions: dict[str, dict[Any, float]] = Field(default_factory=dict)


class CohortDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort_key: str = Field(min_length=1)
    filters: dict[str, Any] = Field(default_factory=dict)
    sampling_mode: Literal["STRATIFIED", "WEIGHTED"] = "STRATIFIED"
    strata: tuple[str, ...] = ()
    per_cell: int = Field(default=1, ge=1)
    sample_size: int | None = Field(default=None, ge=1)
    seed: int
    weight_dimension: str | None = None
    weights: dict[Any, float] = Field(default_factory=dict)
    required_cells: tuple[dict[str, Any], ...] = ()

    @field_validator("strata")
    @classmethod
    def strata_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("strata must be unique")
        return value


class FeasibilityCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    values: dict[str, Any]
    available: int
    required: int
    feasible: bool


class CohortFeasibilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort_key: str
    feasible: bool
    total_available: int
    cells: tuple[FeasibilityCell, ...]
    errors: tuple[str, ...] = ()


class DistributionToleranceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    population_count: int
    expected: dict[str, float]
    observed: dict[str, float]
    absolute_deviation: dict[str, float]
    tolerance: float
    within_tolerance: bool


class PopulationLevel(StrEnum):
    STATISTICAL = "STATISTICAL"
    MATERIALIZED = "MATERIALIZED"
    ACTIVE = "ACTIVE"


class PopulationMember(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: uuid.UUID
    level: PopulationLevel
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    persistent_state: dict[str, Any] = Field(default_factory=dict)
    active_state: dict[str, Any] = Field(default_factory=dict)
    compressed_state: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=0, ge=0)
    world_step: int = Field(default=0, ge=0)


class PopulationTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    transition_id: uuid.UUID
    sequence: int = Field(ge=1)
    persona_id: uuid.UUID
    world_id: uuid.UUID | None = None
    branch_id: uuid.UUID | None = None
    lifecycle_version: int = Field(ge=1)
    from_level: PopulationLevel
    to_level: PopulationLevel
    reason: str
    world_step: int = Field(ge=0)
    persistent_state_hash: str
    active_state_hash: str

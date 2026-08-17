from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DimensionSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    domain_pack: str = "core"
    kind: Literal["enum", "integer", "number", "boolean"]
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    default: Any = None
    depends_on: dict[str, tuple[Any, ...]] = Field(default_factory=dict)


class DomainPackMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    pack_id: str
    version: str
    description: str = ""


class PersonaConstraint(BaseModel):
    """A declarative conditional requirement or incompatibility rule."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    when: dict[str, tuple[Any, ...]] = Field(default_factory=dict)
    require: dict[str, tuple[Any, ...]] = Field(default_factory=dict)
    forbid: dict[str, tuple[Any, ...]] = Field(default_factory=dict)
    message: str = ""


class FieldProvenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal["fixed", "default", "seeded_generator", "weighted_distribution"]
    generator_version: str
    schema_version: str
    domain_pack: str
    seed: int
    distribution: dict[str, float] = Field(default_factory=dict)
    constraint_rules: tuple[str, ...] = ()

    def __getitem__(self, name: str) -> Any:
        """Retain the v2-alpha mapping-style read contract."""
        return getattr(self, name)


class PersonaValidation(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["valid", "invalid"]
    ruleset_version: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    active_dimensions: tuple[str, ...] = ()


class PersonaBlueprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    schema_version: str
    seed: int
    generator_version: str
    source: Literal["synthetic", "manual", "imported"]
    dimensions: dict[str, Any]
    derived_traits: dict[str, float | int | str | bool]
    provenance: dict[str, FieldProvenance]
    validation: PersonaValidation


class CompiledPersona(BaseModel):
    model_config = ConfigDict(frozen=True)

    persona_id: uuid.UUID
    persona_version: str
    compiler_version: str
    identity_summary: str
    policy_weights: dict[str, float]
    starting_goals: tuple[str, ...]
    retrieval_filters: tuple[str, ...]
    starting_beliefs: tuple[dict[str, Any], ...] = ()
    starting_relationships: tuple[dict[str, Any], ...] = ()
    routines: tuple[dict[str, Any], ...] = ()
    capability_modifiers: dict[str, float] = Field(default_factory=dict)
    deep_traits: dict[str, Any] = Field(default_factory=dict)


class PromptAssembly(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    estimated_tokens: int
    character_count: int
    max_tokens: int
    max_characters: int
    included_traits: tuple[str, ...] = ()
    truncated: bool = False


class StratumFeasibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    feasible: bool
    fixed: dict[str, Any]
    errors: tuple[str, ...] = ()


class PersonaVersionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: uuid.UUID
    blueprint: PersonaBlueprint
    content_hash: str
    parent_version_id: uuid.UUID | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

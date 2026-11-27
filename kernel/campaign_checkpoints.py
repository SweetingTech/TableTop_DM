from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from kernel.snapshots import SnapshotEntity, publish_immutable_artifact
from kernel.state import stable_hash

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CheckpointFormat = Literal["tabletop.campaign-checkpoint/v1"]
CHECKPOINT_FORMAT: CheckpointFormat = "tabletop.campaign-checkpoint/v1"


class CheckpointModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class CheckpointBoundary(CheckpointModel):
    world_id: uuid.UUID
    branch_id: uuid.UUID
    continuation_epoch: int = Field(ge=0)
    capture_request_id: uuid.UUID
    trigger_event_id: uuid.UUID | None = None
    trigger_schedule_id: uuid.UUID | None = None
    schema_version: int = Field(ge=1)
    projection_version: int = Field(ge=0)
    state_hash: Digest
    command_ordinal: int = Field(ge=0)
    through_event_seq: int = Field(ge=0)
    through_event_id: uuid.UUID | None
    simulated_seconds: int | None = Field(ge=0)

    @model_validator(mode="after")
    def validate_cut(self) -> Self:
        if (self.through_event_seq == 0) != (self.through_event_id is None):
            raise ValueError("the event boundary must include both event identity and sequence")
        if self.command_ordinal and not self.through_event_seq:
            raise ValueError("a committed command boundary requires an event prefix")
        if self.trigger_event_id is not None and self.through_event_id is None:
            raise ValueError("an event-triggered checkpoint requires a nonempty event prefix")
        return self


class CheckpointSection(StrEnum):
    PHYSICAL_EVIDENCE = "physical_evidence"
    MINDS = "minds"
    POPULATION = "population"
    CHARACTER_RUNTIME = "character_runtime"
    ACTIVITIES_AND_CLOCK = "activities_and_clock"
    RANDOMNESS = "randomness"
    PENDING_WORK = "pending_work"
    STORY = "story"
    NARRATION = "narration"
    RETRIEVAL = "retrieval"
    VERSIONED_ARTIFACTS = "versioned_artifacts"


SECTION_MODES = {
    CheckpointSection.PHYSICAL_EVIDENCE: {"PINNED"},
    CheckpointSection.MINDS: {"FROZEN"},
    CheckpointSection.POPULATION: {"FROZEN"},
    CheckpointSection.CHARACTER_RUNTIME: {"FROZEN"},
    CheckpointSection.ACTIVITIES_AND_CLOCK: {"FROZEN"},
    CheckpointSection.RANDOMNESS: {"FROZEN"},
    CheckpointSection.PENDING_WORK: {"FROZEN"},
    CheckpointSection.STORY: {"FROZEN", "ABSENT"},
    CheckpointSection.NARRATION: {"FROZEN"},
    CheckpointSection.RETRIEVAL: {"REBUILD"},
    CheckpointSection.VERSIONED_ARTIFACTS: {"PINNED"},
}


class CheckpointReference(CheckpointModel):
    kind: str = Field(min_length=1, max_length=100)
    identity: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=150)
    digest: Digest


class CheckpointComponent(CheckpointModel):
    schema_id: str = Field(min_length=1, max_length=150)


class FrozenComponent(CheckpointComponent):
    mode: Literal["FROZEN"] = "FROZEN"
    data: dict[str, JsonValue] = Field(repr=False)


class ReferencedComponent(CheckpointComponent):
    references: tuple[CheckpointReference, ...] = Field(repr=False)

    @model_validator(mode="after")
    def validate_reference_order(self) -> Self:
        identities = [(item.kind, item.identity, item.version) for item in self.references]
        if identities != sorted(set(identities)):
            raise ValueError("checkpoint references require a unique stable order")
        return self


class PinnedComponent(ReferencedComponent):
    mode: Literal["PINNED"] = "PINNED"


class RebuildComponent(ReferencedComponent):
    mode: Literal["REBUILD"] = "REBUILD"
    builder_version: str = Field(min_length=1, max_length=150)


class AbsentComponent(CheckpointComponent):
    mode: Literal["ABSENT"] = "ABSENT"
    reason: Literal["STORY_NOT_INSTALLED"]


Component = Annotated[
    FrozenComponent | PinnedComponent | RebuildComponent | AbsentComponent,
    Field(discriminator="mode"),
]


class CampaignCheckpoint(CheckpointModel):
    format: CheckpointFormat = CHECKPOINT_FORMAT
    boundary: CheckpointBoundary
    projections: dict[str, dict[str, JsonValue]] = Field(repr=False)
    entities: dict[str, SnapshotEntity] = Field(repr=False)
    sections: dict[CheckpointSection, Component] = Field(repr=False)

    @model_validator(mode="after")
    def validate_components(self) -> Self:
        if stable_hash(self.projections) != self.boundary.state_hash:
            raise ValueError("checkpoint projection does not match the causal boundary")
        if set(self.entities) != set(self.projections.get("tabletop.entities", {})):
            raise ValueError("checkpoint requires metadata for every projected entity")
        for key, entity in self.entities.items():
            if (key, entity.world_id, entity.branch_id) != (
                str(entity.entity_id),
                self.boundary.world_id,
                self.boundary.branch_id,
            ):
                raise ValueError("checkpoint entity metadata belongs to a different scope")
        if set(self.sections) != set(CheckpointSection):
            raise ValueError("checkpoint has an incomplete component inventory")
        for section, value in self.sections.items():
            if value.mode not in SECTION_MODES[section]:
                raise ValueError("checkpoint component has an invalid disposition")
        evidence = self.sections[CheckpointSection.PHYSICAL_EVIDENCE]
        if (
            self.boundary.through_event_seq
            and isinstance(evidence, PinnedComponent)
            and not evidence.references
        ):
            raise ValueError("event boundary requires pinned evidence")
        return self

    def component_digests(self) -> dict[str, str]:
        digests = {
            "projection": self.boundary.state_hash,
            "entity_metadata": stable_hash(
                {key: entity.model_dump(mode="json") for key, entity in self.entities.items()}
            ),
        }
        digests.update(
            (section.value, stable_hash(value.model_dump(mode="json")))
            for section, value in self.sections.items()
        )
        return digests


class CampaignCheckpointManifest(CheckpointModel):
    format: CheckpointFormat = CHECKPOINT_FORMAT
    checkpoint_id: uuid.UUID
    boundary: CheckpointBoundary
    component_digests: dict[str, Digest] = Field(repr=False)
    artifact_hash: Digest


class CampaignCheckpointStore:
    """Private content-addressed files for complete campaign checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, manifest: CampaignCheckpointManifest) -> Path:
        return self.root / str(manifest.boundary.world_id) / f"{manifest.checkpoint_id}.json.gz"

    def create(self, checkpoint: CampaignCheckpoint) -> CampaignCheckpointManifest:
        # Revalidate on the serialization boundary because nested JSON is mutable in Python.
        checkpoint = CampaignCheckpoint.model_validate(checkpoint.model_dump(mode="json"))
        body = json.dumps(
            checkpoint.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        compressed = gzip.compress(body, mtime=0)
        manifest = self._manifest(checkpoint, compressed)
        publish_immutable_artifact(self._path(manifest), compressed)
        return manifest

    def load(self, manifest: CampaignCheckpointManifest) -> CampaignCheckpoint:
        compressed = self._path(manifest).read_bytes()
        if hashlib.sha256(compressed).hexdigest() != manifest.artifact_hash:
            raise ValueError("checkpoint artifact hash mismatch")
        checkpoint = CampaignCheckpoint.model_validate_json(gzip.decompress(compressed))
        if self._manifest(checkpoint, compressed) != manifest:
            raise ValueError("checkpoint artifact differs from its manifest")
        return checkpoint

    @staticmethod
    def _manifest(checkpoint: CampaignCheckpoint, compressed: bytes) -> CampaignCheckpointManifest:
        digests = checkpoint.component_digests()
        identity = stable_hash(
            {
                "format": checkpoint.format,
                "boundary": checkpoint.boundary.model_dump(mode="json"),
                "component_digests": digests,
            }
        )
        return CampaignCheckpointManifest(
            checkpoint_id=uuid.uuid5(uuid.NAMESPACE_URL, f"tabletop-dm:checkpoint:{identity}"),
            boundary=checkpoint.boundary,
            component_digests=digests,
            artifact_hash=hashlib.sha256(compressed).hexdigest(),
        )

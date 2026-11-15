from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kernel.state import stable_hash


class SnapshotEntity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    entity_type: str
    name: str
    controller_actor_id: uuid.UUID | None = None
    secret_state: dict[str, Any] = Field(default_factory=dict)


class SnapshotManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    through_event_seq: int
    state_hash: str
    artifact_uri: str
    artifact_hash: str
    contract_version: str = "2.0.0"


class SnapshotStore:
    """Content-addressed local artifact store with deterministic gzip bundles."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def create(
        self,
        world_id: uuid.UUID,
        branch_id: uuid.UUID,
        through_event_seq: int,
        projections: dict[str, Any],
        *,
        entities: dict[str, Any] | None = None,
    ) -> SnapshotManifest:
        state_hash = stable_hash(projections)
        version = "2.0.0" if entities is None else "2.1.0"
        frozen_entities = None
        if entities is not None:
            frozen_entities = {}
            for key, raw in sorted(entities.items()):
                entity = SnapshotEntity.model_validate(raw)
                if (str(entity.entity_id), entity.world_id, entity.branch_id) != (
                    key,
                    world_id,
                    branch_id,
                ):
                    raise ValueError("snapshot entity lineage differs from source branch")
                frozen_entities[key] = entity.model_dump(mode="json")
            if set(frozen_entities) != set(projections.get("tabletop.entities", {})):
                raise ValueError("snapshot must contain metadata for every embodied entity")
        identity_hash = (
            state_hash
            if frozen_entities is None
            else stable_hash({"projections": projections, "entities": frozen_entities})
        )
        snapshot_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:snapshot:{world_id}:{branch_id}:{through_event_seq}:{identity_hash}",
        )
        body = json.dumps(
            {
                "snapshot_id": str(snapshot_id),
                "world_id": str(world_id),
                "branch_id": str(branch_id),
                "through_event_seq": through_event_seq,
                "contract_version": version,
                "state_hash": state_hash,
                "projections": projections,
                **({"entities": frozen_entities} if frozen_entities is not None else {}),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
        compressed = gzip.compress(body, mtime=0)
        artifact_hash = hashlib.sha256(compressed).hexdigest()
        destination = self.root / str(world_id) / f"{snapshot_id}.json.gz"
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(compressed)
        try:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != compressed:
                    raise ValueError(
                        "immutable snapshot artifact differs from frozen content"
                    ) from None
        finally:
            temporary.unlink(missing_ok=True)
        return SnapshotManifest(
            snapshot_id=snapshot_id,
            world_id=world_id,
            branch_id=branch_id,
            through_event_seq=through_event_seq,
            state_hash=state_hash,
            artifact_uri=destination.as_uri(),
            artifact_hash=artifact_hash,
            contract_version=version,
        )

    @staticmethod
    def load(manifest: SnapshotManifest) -> dict[str, Any]:
        path = Path(manifest.artifact_uri.removeprefix("file:///"))
        if not path.exists() and manifest.artifact_uri.startswith("file:///"):
            path = Path("/" + manifest.artifact_uri.removeprefix("file:///"))
        compressed = path.read_bytes()
        if hashlib.sha256(compressed).hexdigest() != manifest.artifact_hash:
            raise ValueError("Snapshot artifact hash mismatch")
        payload = json.loads(gzip.decompress(compressed))
        if stable_hash(payload["projections"]) != manifest.state_hash:
            raise ValueError("Snapshot state hash mismatch")
        for key, expected in {
            "snapshot_id": str(manifest.snapshot_id),
            "world_id": str(manifest.world_id),
            "branch_id": str(manifest.branch_id),
            "through_event_seq": manifest.through_event_seq,
            "contract_version": manifest.contract_version,
            "state_hash": manifest.state_hash,
        }.items():
            if payload.get(key) != expected:
                raise ValueError("Snapshot manifest differs from its artifact")
        if manifest.contract_version == "2.1.0":
            entities = payload.get("entities")
            if not isinstance(entities, dict) or set(entities) != set(
                payload["projections"].get("tabletop.entities", {})
            ):
                raise ValueError("snapshot entity metadata is incomplete")
            for key, raw in entities.items():
                entity = SnapshotEntity.model_validate(raw)
                if (str(entity.entity_id), entity.world_id, entity.branch_id) != (
                    key,
                    manifest.world_id,
                    manifest.branch_id,
                ):
                    raise ValueError("snapshot entity lineage differs from source branch")
        elif manifest.contract_version != "2.0.0":
            raise ValueError("unsupported snapshot contract")
        identity_hash = (
            stable_hash({"projections": payload["projections"], "entities": payload["entities"]})
            if manifest.contract_version == "2.1.0"
            else manifest.state_hash
        )
        expected_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:snapshot:{manifest.world_id}:{manifest.branch_id}:"
            f"{manifest.through_event_seq}:{identity_hash}",
        )
        if expected_id != manifest.snapshot_id:
            raise ValueError("snapshot identity does not match frozen content")
        return payload

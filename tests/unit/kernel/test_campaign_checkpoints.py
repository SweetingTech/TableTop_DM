from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from kernel.campaign_checkpoints import (
    AbsentComponent,
    CampaignCheckpoint,
    CampaignCheckpointStore,
    CheckpointBoundary,
    CheckpointReference,
    CheckpointSection,
    FrozenComponent,
    PinnedComponent,
    RebuildComponent,
)
from kernel.snapshots import SnapshotEntity, SnapshotStore
from kernel.state import stable_hash

pytestmark = pytest.mark.unit


def checkpoint() -> CampaignCheckpoint:
    world, branch, entity, event, request = (uuid.uuid4() for _ in range(5))
    projections = {"tabletop.entities": {str(entity): {"hp": 9}}}
    boundary = CheckpointBoundary(
        world_id=world,
        branch_id=branch,
        continuation_epoch=4,
        capture_request_id=request,
        schema_version=20,
        projection_version=9,
        state_hash=stable_hash(projections),
        command_ordinal=8,
        through_event_seq=91,
        through_event_id=event,
        simulated_seconds=600,
    )
    entity_metadata = SnapshotEntity(
        entity_id=entity,
        world_id=world,
        branch_id=branch,
        entity_type="NPC",
        name="Ferryman",
        secret_state={"location": "Blue lantern"},
    )
    prefix = CheckpointReference(
        kind="physical-evidence-prefix",
        identity=str(event),
        version="1",
        digest=stable_hash([str(event)]),
    )
    return CampaignCheckpoint(
        boundary=boundary,
        projections=projections,
        entities={str(entity): entity_metadata},
        sections={
            CheckpointSection.PHYSICAL_EVIDENCE: PinnedComponent(
                schema_id="physical-evidence/v1", references=(prefix,)
            ),
            CheckpointSection.MINDS: FrozenComponent(
                schema_id="minds/v1", data={"observations": []}
            ),
            CheckpointSection.POPULATION: FrozenComponent(schema_id="population/v1", data={}),
            CheckpointSection.CHARACTER_RUNTIME: FrozenComponent(
                schema_id="character-runtime/v1", data={}
            ),
            CheckpointSection.ACTIVITIES_AND_CLOCK: FrozenComponent(
                schema_id="time/v1", data={"seconds": boundary.simulated_seconds}
            ),
            CheckpointSection.RANDOMNESS: FrozenComponent(
                schema_id="randomness/v1", data={"ordinal": boundary.command_ordinal}
            ),
            CheckpointSection.PENDING_WORK: FrozenComponent(schema_id="pending-work/v1", data={}),
            CheckpointSection.STORY: AbsentComponent(
                schema_id="story/v1", reason="STORY_NOT_INSTALLED"
            ),
            CheckpointSection.NARRATION: FrozenComponent(schema_id="narration/v1", data={}),
            CheckpointSection.RETRIEVAL: RebuildComponent(
                schema_id="retrieval/v1", builder_version="one", references=(prefix,)
            ),
            CheckpointSection.VERSIONED_ARTIFACTS: PinnedComponent(
                schema_id="versioned-artifacts/v1", references=()
            ),
        },
    )


def test_complete_checkpoint_is_immutable_and_can_load_after_restart(tmp_path):
    payload = checkpoint()
    store = CampaignCheckpointStore(tmp_path / "checkpoints")
    first = store.create(payload)
    assert store.create(payload) == first
    assert "Blue lantern" not in str(first.model_dump(mode="json"))
    assert len(first.component_digests) == len(CheckpointSection) + 2
    assert CampaignCheckpointStore(store.root).load(first) == payload

    # Legacy replay/trial artifacts remain separate and use the unchanged writer.
    old_store = SnapshotStore(tmp_path / "snapshots")
    old = old_store.create(
        payload.boundary.world_id, payload.boundary.branch_id, 8, payload.projections
    )
    assert SnapshotStore.load(old)["projections"] == payload.projections


@pytest.mark.parametrize("change", ["missing_minds", "absent_minds", "foreign_entity", "event_cut"])
def test_checkpoint_rejects_incomplete_or_cross_scoped_data(change):
    raw = checkpoint().model_dump(mode="json")
    if change == "missing_minds":
        del raw["sections"]["minds"]
    elif change == "absent_minds":
        raw["sections"]["minds"] = raw["sections"]["story"]
    elif change == "foreign_entity":
        next(iter(raw["entities"].values()))["branch_id"] = str(uuid.uuid4())
    else:
        raw["boundary"]["through_event_id"] = None
    with pytest.raises(ValidationError) as exc:
        CampaignCheckpoint.model_validate(raw)
    assert "Blue lantern" not in str(exc.value)


def test_store_validates_mutated_payload_and_detects_corrupt_artifact(tmp_path):
    payload = checkpoint()
    store = CampaignCheckpointStore(tmp_path)
    manifest = store.create(payload)
    bad_digests = {**manifest.component_digests, "minds": stable_hash("different")}
    with pytest.raises(ValueError, match="differs from its manifest"):
        store.load(manifest.model_copy(update={"component_digests": bad_digests}))
    artifact = tmp_path / str(payload.boundary.world_id) / f"{manifest.checkpoint_id}.json.gz"
    artifact.write_bytes(b"bad bytes")
    with pytest.raises(ValueError, match="artifact hash mismatch"):
        store.load(manifest)
    payload.projections["tabletop.entities"].clear()
    with pytest.raises(ValidationError, match="does not match the causal boundary"):
        store.create(payload)

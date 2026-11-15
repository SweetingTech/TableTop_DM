from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from kernel.application import SimulationApplication
from kernel.contracts import CommandProposal
from kernel.snapshots import SnapshotStore, artifact_path

pytestmark = pytest.mark.unit


def nested_world(tmp_path):
    app = SimulationApplication(tmp_path)
    ids = app.bootstrap_demo()
    initial = app.create_snapshot(ids["world_id"])
    trial, run = app.create_trial(ids["world_id"], initial.snapshot_id, 101)
    child = uuid.uuid4()
    app.submit(
        CommandProposal(
            world_id=ids["world_id"],
            branch_id=trial.branch_id,
            run_id=run.run_id,
            actor_id=ids["actor_id"],
            command_type="tabletop.entity.spawn",
            idempotency_key="trial-child",
            parameters={
                "entity_id": str(child),
                "name": "Trial child",
                "entity_type": "NPC",
                "controller_actor_id": str(ids["actor_id"]),
                "secret_state": {"identity": "PAST_SECRET"},
                "public_state": {"x": 12, "y": 12, "hp": 17},
            },
        )
    )
    return app, ids, trial, run, child


def test_nested_trial_restores_exact_frozen_metadata_and_excludes_later_entities(tmp_path):
    app, ids, trial, run, child = nested_world(tmp_path)
    snapshot = app.create_branch_snapshot(trial.branch_id)
    app.entities[(trial.branch_id, child)].secret_state["identity"] = "FUTURE_SECRET"
    app.create_entity(
        ids["world_id"],
        ids["branch_id"],
        "Canonical decoy",
        "NPC",
        {"hp": 99},
        entity_id=child,
        secret_state={"identity": "CANONICAL_SECRET"},
    )
    canonical = app.states.get(ids["branch_id"]).state_hash
    branch, nested_run = app.create_trial(ids["world_id"], snapshot.snapshot_id, 102)
    record = app.entities[(branch.branch_id, child)]
    assert record.secret_state == {"identity": "PAST_SECRET"}
    assert record.name == "Trial child" and record.public_state["hp"] == 17
    assert record.controller_actor_id == ids["actor_id"]
    assert app.branch_snapshot_ids[branch.branch_id] == snapshot.snapshot_id
    assert app.states.get(ids["branch_id"]).state_hash == canonical
    before = app.states.get(branch.branch_id).state_hash
    assert app.create_trial(ids["world_id"], snapshot.snapshot_id, 102) == (branch, nested_run)
    assert app.states.get(branch.branch_id).state_hash == before


def test_metadata_changes_have_distinct_snapshot_identity_without_duplicate_body_state(tmp_path):
    app, ids, trial, run, child = nested_world(tmp_path)
    first = app.create_branch_snapshot(trial.branch_id)
    app.entities[(trial.branch_id, child)].secret_state["identity"] = "LATER"
    second = app.create_branch_snapshot(trial.branch_id)
    assert first.state_hash == second.state_hash and first.snapshot_id != second.snapshot_id
    assert SnapshotStore.load(first)["entities"][str(child)]["secret_state"] == {
        "identity": "PAST_SECRET"
    }
    assert "public_state" not in SnapshotStore.load(first)["entities"][str(child)]
    assert app.create_branch_snapshot(trial.branch_id) == second


def test_legacy_projection_snapshots_remain_readable_but_fail_closed_for_new_restoration(tmp_path):
    app = SimulationApplication(tmp_path)
    ids = app.bootstrap_demo()
    state = app.states.get(ids["branch_id"])
    legacy = app.snapshot_store.create(ids["world_id"], ids["branch_id"], 0, state.projections)
    app.snapshots[legacy.snapshot_id] = legacy
    assert SnapshotStore.load(legacy)["projections"] == state.projections
    before = (len(app.states.all()), len(app.entities), len(app.runs))
    with pytest.raises(ValueError, match="frozen entity metadata"):
        app.create_trial(ids["world_id"], legacy.snapshot_id, 23)
    assert (len(app.states.all()), len(app.entities), len(app.runs)) == before


def test_identical_concurrent_artifact_writes_are_readable_and_idempotent(tmp_path):
    store = SnapshotStore(tmp_path)
    world, branch = uuid.uuid4(), uuid.uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        manifests = list(
            pool.map(lambda _: store.create(world, branch, 0, {"counter": 1}), range(16))
        )
    assert all(manifest == manifests[0] for manifest in manifests)
    assert SnapshotStore.load(manifests[0])["projections"] == {"counter": 1}


def test_corrupt_metadata_cannot_partially_publish_a_trial(tmp_path):
    app, ids, trial, run, child = nested_world(tmp_path)
    snapshot = app.create_branch_snapshot(trial.branch_id)
    body = SnapshotStore.load(snapshot)
    body["entities"][str(child)]["secret_state"] = {"identity": "FORGED"}
    data = gzip.compress(json.dumps(body).encode(), mtime=0)
    artifact = app.snapshot_store.root / str(snapshot.world_id) / f"{snapshot.snapshot_id}.json.gz"
    artifact.write_bytes(data)
    changed = snapshot.model_copy(update={"artifact_hash": hashlib.sha256(data).hexdigest()})
    app.snapshots[snapshot.snapshot_id] = changed
    before = (len(app.states.all()), len(app.entities), len(app.runs))
    with pytest.raises(ValueError, match="identity"):
        app.create_trial(ids["world_id"], snapshot.snapshot_id, 55)
    assert (len(app.states.all()), len(app.entities), len(app.runs)) == before


@pytest.mark.parametrize("name", ["folder with spaces", "literal %20 directory", "café 雪"])
def test_local_artifact_uri_roundtrips_exactly_once_and_restores_trials(tmp_path, name):
    app = SimulationApplication(tmp_path / name)
    ids = app.bootstrap_demo()
    current = app.create_snapshot(ids["world_id"])
    state = app.states.get(ids["branch_id"])
    legacy = app.snapshot_store.create(ids["world_id"], ids["branch_id"], 0, state.projections)
    assert SnapshotStore.load(legacy)["projections"] == state.projections
    branch, run = app.create_trial(ids["world_id"], current.snapshot_id, 510)
    assert app.entities[(branch.branch_id, ids["hero_id"])].name == "Aster Vale"


@pytest.mark.parametrize(
    "uri", ["https://example.invalid/data", "file://remote/data", "file:relative", "/plain/path"]
)
def test_artifacts_do_not_follow_remote_or_relative_uri_targets(uri):
    with pytest.raises(ValueError):
        artifact_path(uri)

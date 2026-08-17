import uuid

import pytest

from experiments.calibration import CalibrationEngine
from kernel.snapshots import SnapshotStore
from population import PopulationStore

pytestmark = pytest.mark.unit


def test_snapshot_bundle_is_content_addressed_and_verified(tmp_path):
    store = SnapshotStore(tmp_path / "snapshots")
    world_id, branch_id = uuid.uuid4(), uuid.uuid4()
    projections = {"entities": {"one": {"hp": 8}}}
    first = store.create(world_id, branch_id, 17, projections)
    second = store.create(world_id, branch_id, 17, projections)
    assert first == second
    assert SnapshotStore.load(first)["projections"] == projections


def test_population_store_filters_and_stratifies_seeded_personas(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    store.generate(size=80, seed=17)
    assert store.count() == 80
    explorer_count = store.count({"player_style": "EXPLORER"})
    sample = store.sample_stratified(strata=("rules_familiarity",), per_cell=2, seed=99)
    repeated = store.sample_stratified(strata=("rules_familiarity",), per_cell=2, seed=99)
    assert explorer_count >= 0
    assert sample == repeated
    assert len(sample) <= 8


def test_calibration_requires_review_and_never_claims_ground_truth():
    report = CalibrationEngine().compare(
        synthetic_metrics={"completion_rate": 0.9, "mean_steps": 7.0},
        human_metrics={"completion_rate": 0.75, "mean_steps": 8.0},
        policy_version="onboarding-policy-1.0.0",
        evidence_version="local-playtests-1",
    )
    assert report.promotion_status == "REVIEW_REQUIRED"
    assert report.human_ground_truth_claimed is False
    assert report.root_mean_squared_error > 0

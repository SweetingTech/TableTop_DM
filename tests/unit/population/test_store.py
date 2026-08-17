from __future__ import annotations

from collections import Counter

import pyarrow.parquet as pq
import pytest

from population.models import CohortDefinition, PopulationDefinition
from population.store import PopulationStore

pytestmark = pytest.mark.unit


def test_population_generation_writes_bounded_parquet_row_groups(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    definition = PopulationDefinition(
        population_key="test-town",
        version="1.0.0",
        size=53,
        seed=11,
        fixed={"rules_familiarity": "LOW"},
    )

    store.generate_definition(definition, batch_size=7)
    metadata = pq.ParquetFile(store.path).metadata

    assert metadata.num_rows == 53
    assert metadata.num_row_groups == 8
    assert store.count() == 53
    assert store.count({"rules_familiarity": "LOW"}) == 53


def test_duckdb_stratified_sampling_is_seeded_and_bounded_per_cell(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    store.generate(240, 12, batch_size=31)

    first = store.sample_stratified(("rules_familiarity", "player_style"), 2, 99)
    repeated = store.sample_stratified(("rules_familiarity", "player_style"), 2, 99)
    counts = Counter((row["rules_familiarity"], row["player_style"]) for row in first)

    assert first == repeated
    assert first
    assert all(count <= 2 for count in counts.values())


def test_duckdb_weighted_sampling_is_seeded_and_respects_allowed_values(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    store.generate(300, 13, batch_size=37)
    weights = {"EXPLORER": 20, "BALANCED": 1}

    first = store.sample_weighted(12, 7, "player_style", weights)
    repeated = store.sample_weighted(12, 7, "player_style", weights)

    assert first == repeated
    assert len(first) == 12
    assert {row["player_style"] for row in first} <= set(weights)
    assert sum(row["player_style"] == "EXPLORER" for row in first) >= 8


def test_cohort_feasibility_and_reusable_sampling_contract(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    store.generate_definition(
        PopulationDefinition(
            population_key="novices",
            version="1",
            size=80,
            seed=2,
            fixed={"rules_familiarity": "LOW"},
        ),
        batch_size=17,
    )
    feasible = CohortDefinition(
        cohort_key="low-rules",
        filters={"rules_familiarity": "LOW"},
        strata=("rules_familiarity",),
        per_cell=10,
        seed=3,
    )
    impossible = feasible.model_copy(
        update={
            "cohort_key": "requires-high",
            "required_cells": ({"rules_familiarity": "HIGH"},),
        }
    )

    good_report = store.cohort_feasibility(feasible)
    bad_report = store.cohort_feasibility(impossible)
    sample = store.sample_cohort(feasible)

    assert good_report.feasible is True
    assert bad_report.feasible is False
    assert bad_report.errors
    assert len(sample) == 10
    assert all(row["rules_familiarity"] == "LOW" for row in sample)

    weighted_impossible = CohortDefinition(
        cohort_key="missing-high",
        filters={"rules_familiarity": "LOW"},
        sampling_mode="WEIGHTED",
        sample_size=1,
        seed=4,
        weight_dimension="rules_familiarity",
        weights={"HIGH": 1},
    )
    weighted_report = store.cohort_feasibility(weighted_impossible)
    assert weighted_report.feasible is False
    with pytest.raises(ValueError, match="needs 1, found 0"):
        store.sample_weighted(
            1,
            4,
            "rules_familiarity",
            {"HIGH": 1},
            {"rules_familiarity": "LOW"},
        )


def test_distribution_tolerance_reports_observed_deviation(tmp_path):
    store = PopulationStore(tmp_path / "population.parquet")
    expected = {"LOW": 1, "HIGH": 3}
    store.generate_definition(
        PopulationDefinition(
            population_key="risk-pool",
            version="1",
            size=500,
            seed=44,
            distributions={"risk_tolerance": expected},
        ),
        batch_size=73,
    )

    report = store.distribution_tolerance("risk_tolerance", expected, tolerance=0.1)

    assert report.population_count == 500
    assert report.expected == {"HIGH": 0.75, "LOW": 0.25}
    assert report.within_tolerance is True
    assert set(report.absolute_deviation) == {"HIGH", "LOW"}

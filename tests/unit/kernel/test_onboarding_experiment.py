import pytest

from experiments.onboarding import OnboardingExperiment

pytestmark = pytest.mark.unit


def test_onboarding_cohort_is_reproducible_and_branch_isolated():
    experiment = OnboardingExperiment()
    first = experiment.run_cohort(cohort_size=4, seeds=(101, 202), include_trials=8)
    second = experiment.run_cohort(cohort_size=4, seeds=(101, 202), include_trials=8)
    assert first == second
    assert first.trial_count == 8
    assert first.canonical_world_unchanged is True
    assert all(
        trial.canonical_hash_before == trial.canonical_hash_after for trial in first.sample_trials
    )
    assert all(trial.traces for trial in first.sample_trials)


def test_onboarding_verifiers_emit_normalized_facts():
    report = OnboardingExperiment().run_cohort(cohort_size=1, seeds=(303,), include_trials=1)
    fact_types = {fact.fact_type for fact in report.sample_trials[0].facts}
    assert "onboarding.completed" in fact_types
    assert "onboarding.invalid_action_count" in fact_types
    assert "kernel.canonical_world_unchanged" in fact_types

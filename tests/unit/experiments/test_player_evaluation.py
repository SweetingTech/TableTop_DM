from __future__ import annotations

import uuid

import pytest

from experiments.onboarding import OnboardingExperiment
from experiments.player_evaluation import PlayerEvaluationVerifier
from kernel.contracts import EventEnvelopeV2

pytestmark = pytest.mark.unit


def _event(number: int, event_type: str, payload: dict) -> EventEnvelopeV2:
    actor_id = uuid.UUID(int=2000)
    return EventEnvelopeV2(
        event_id=uuid.UUID(int=number),
        world_id=uuid.UUID(int=2001),
        branch_id=uuid.UUID(int=2002),
        run_id=uuid.UUID(int=2003),
        actor_id=actor_id,
        event_type=event_type,
        payload=payload,
        visible_to=(actor_id,),
        correlation_id=uuid.UUID(int=2004),
    )


def test_player_verifier_normalizes_behavioral_and_quality_failures():
    events = (
        _event(
            1,
            "tabletop.action",
            {"action": "JUMP", "outcome": "INVALID", "invalid_reason": "blocked"},
        ),
        _event(
            2,
            "tabletop.action",
            {"action": "JUMP", "outcome": "INVALID", "invalid_reason": "blocked"},
        ),
        _event(3, "tabletop.action", {"action": "MOVE", "outcome": "VALID"}),
        _event(4, "ui.hint", {"hint_provided": True}),
        _event(5, "character.death", {"died": True}),
        _event(6, "accessibility.blocked", {"inaccessible": True}),
        _event(
            7,
            "narrative.contradiction",
            {"narrative_contradiction": True},
        ),
        _event(8, "clue.discovered", {"clue_discovered": True}),
    )
    result = PlayerEvaluationVerifier().verify(
        events,
        {"dialogue_loops": 2, "abandoned": True, "quest_comprehended": False},
    )

    assert result.metrics.time_to_first_valid_action == 3
    assert result.metrics.invalid_action_reasons == {"blocked": 2}
    assert result.metrics.repeated_failed_actions == 1
    assert result.metrics.abandoned is True
    assert result.metrics.deaths == 1
    assert result.metrics.hints_requested == 1
    assert result.metrics.dialogue_loops == 2
    assert result.metrics.inaccessible_paths == 1
    assert result.metrics.narrative_contradictions == 1
    assert result.metrics.clues_discovered == 1
    fact_types = {fact.fact_type for fact in result.facts}
    assert "player.time_to_first_valid_action" in fact_types
    assert "player.invalid_action_reason" in fact_types


def test_player_verifier_derives_abandonment_dialogue_and_comprehension_from_events():
    events = (
        _event(
            20, "tabletop.action", {"action": "ask_help", "outcome": "HELP_PROVIDED", "step": "A"}
        ),
        _event(
            21, "tabletop.action", {"action": "ASK_HELP", "outcome": "HELP_PROVIDED", "step": "A"}
        ),
        _event(22, "quest.comprehended", {"quest_comprehended": True}),
        _event(23, "session.abandoned", {"abandoned": True}),
    )

    result = PlayerEvaluationVerifier().verify(events, {})

    assert result.metrics.rules_help_requests == 2
    assert result.metrics.dialogue_loops == 1
    assert result.metrics.quest_comprehended is True
    assert result.metrics.abandoned is True
    facts = {fact.fact_type: fact for fact in result.facts}
    assert facts["player.rules_help_requests"].value == 2
    assert facts["player.dialogue_loops"].evidence_event_ids == (uuid.UUID(int=21),)
    assert facts["player.abandoned"].evidence_event_ids == (uuid.UUID(int=23),)


def test_onboarding_compatibility_surface_includes_expanded_playtest_metrics():
    report = OnboardingExperiment().run_cohort(
        cohort_size=2,
        seeds=(101,),
        include_trials=2,
    )

    assert report.trial_count == 2
    assert "mean_time_to_first_valid_action" in report.metrics
    assert "abandonment_rate" in report.metrics
    for trial in report.sample_trials:
        assert "invalid_action_reasons" in trial.metrics
        assert "deaths" in trial.metrics
        assert "inaccessible_paths" in trial.metrics
        assert "narrative_contradictions" in trial.metrics

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kernel.contracts import EventEnvelopeV2, VerifierFact


class PlayerEvaluationMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    time_to_first_valid_action: int = -1
    invalid_actions: int = Field(default=0, ge=0)
    invalid_action_reasons: dict[str, int] = Field(default_factory=dict)
    repeated_failed_actions: int = Field(default=0, ge=0)
    rules_help_requests: int = Field(default=0, ge=0)
    hints_requested: int = Field(default=0, ge=0)
    dialogue_loops: int = Field(default=0, ge=0)
    abandoned: bool = False
    deaths: int = Field(default=0, ge=0)
    inaccessible_paths: int = Field(default=0, ge=0)
    narrative_contradictions: int = Field(default=0, ge=0)
    clues_discovered: int = Field(default=0, ge=0)
    quest_comprehended: bool = False


class PlayerEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    metrics: PlayerEvaluationMetrics
    facts: tuple[VerifierFact, ...]


class PlayerEvaluationVerifier:
    VERSION = "player-evaluation-1.0.0"

    def verify(
        self,
        events: tuple[EventEnvelopeV2, ...],
        final_state: dict[str, Any],
    ) -> PlayerEvaluationResult:
        first_valid = -1
        invalid_reasons: Counter[str] = Counter()
        invalid_evidence: list[uuid.UUID] = []
        invalid_evidence_by_reason: defaultdict[str, list[uuid.UUID]] = defaultdict(list)
        hint_events: list[uuid.UUID] = []
        help_events: list[uuid.UUID] = []
        death_events: list[uuid.UUID] = []
        inaccessible_events: list[uuid.UUID] = []
        contradiction_events: list[uuid.UUID] = []
        clue_events: list[uuid.UUID] = []
        dialogue_loop_events: list[uuid.UUID] = []
        abandoned_events: list[uuid.UUID] = []
        comprehension_events: list[uuid.UUID] = []
        repeated_failures = 0
        prior_invalid_action: str | None = None
        prior_help_step: str | None = None

        for index, event in enumerate(events, start=1):
            payload = event.payload
            outcome = str(payload.get("outcome", "")).upper()
            action = str(payload.get("action", "")).upper()
            if outcome == "VALID" and first_valid < 0:
                first_valid = index
            if outcome == "INVALID":
                reason = str(
                    payload.get("invalid_reason")
                    or payload.get("failure_code")
                    or f"unexpected_action:{action or 'unknown'}"
                )
                invalid_reasons[reason] += 1
                invalid_evidence.append(event.event_id)
                invalid_evidence_by_reason[reason].append(event.event_id)
                if prior_invalid_action == action:
                    repeated_failures += 1
                prior_invalid_action = action
            else:
                prior_invalid_action = None
            event_type = event.event_type.casefold()
            if action == "ASK_HELP" or "rules_help" in event_type:
                help_events.append(event.event_id)
            if "dialogue.loop" in event_type:
                dialogue_loop_events.append(event.event_id)
            elif outcome == "HELP_PROVIDED":
                help_step = str(payload.get("step", ""))
                if help_step and help_step == prior_help_step:
                    dialogue_loop_events.append(event.event_id)
                prior_help_step = help_step
            elif outcome == "VALID":
                prior_help_step = None
            if "hint" in event_type or bool(payload.get("hint_provided")):
                hint_events.append(event.event_id)
            if "death" in event_type or bool(payload.get("died")):
                death_events.append(event.event_id)
            if "accessibility.blocked" in event_type or bool(payload.get("inaccessible")):
                inaccessible_events.append(event.event_id)
            if "narrative.contradiction" in event_type or bool(
                payload.get("narrative_contradiction")
            ):
                contradiction_events.append(event.event_id)
            if "clue.discovered" in event_type or bool(payload.get("clue_discovered")):
                clue_events.append(event.event_id)
            if "abandon" in event_type or bool(payload.get("abandoned")):
                abandoned_events.append(event.event_id)
            if "quest.comprehended" in event_type or bool(payload.get("quest_comprehended")):
                comprehension_events.append(event.event_id)

        state = final_state.get("player_evaluation", final_state)
        metrics = PlayerEvaluationMetrics(
            time_to_first_valid_action=int(state.get("time_to_first_valid_action", first_valid)),
            invalid_actions=int(state.get("invalid_actions", sum(invalid_reasons.values()))),
            invalid_action_reasons=dict(sorted(invalid_reasons.items())),
            repeated_failed_actions=int(state.get("repeated_failed_actions", repeated_failures)),
            rules_help_requests=int(state.get("help_requests", len(help_events))),
            hints_requested=int(state.get("hints_requested", len(hint_events))),
            dialogue_loops=int(state.get("dialogue_loops", len(dialogue_loop_events))),
            abandoned=bool(state.get("abandoned", bool(abandoned_events))),
            deaths=int(state.get("deaths", len(death_events))),
            inaccessible_paths=int(state.get("inaccessible_paths", len(inaccessible_events))),
            narrative_contradictions=int(
                state.get("narrative_contradictions", len(contradiction_events))
            ),
            clues_discovered=int(state.get("clues_discovered", len(clue_events))),
            quest_comprehended=bool(state.get("quest_comprehended", bool(comprehension_events))),
        )
        facts = (
            self._fact(
                "player.time_to_first_valid_action",
                metrics.time_to_first_valid_action,
                tuple(
                    event.event_id for event in events[: max(metrics.time_to_first_valid_action, 0)]
                ),
                "actions",
            ),
            self._fact(
                "player.invalid_action_count",
                metrics.invalid_actions,
                tuple(invalid_evidence),
                "actions",
            ),
            self._fact(
                "player.repeated_failed_actions",
                metrics.repeated_failed_actions,
                tuple(invalid_evidence),
                "actions",
            ),
            self._fact(
                "player.rules_help_requests",
                metrics.rules_help_requests,
                tuple(help_events),
                "requests",
            ),
            self._fact(
                "player.abandoned",
                metrics.abandoned,
                tuple(abandoned_events),
            ),
            self._fact("player.death_count", metrics.deaths, tuple(death_events), "deaths"),
            self._fact(
                "player.hints_requested",
                metrics.hints_requested,
                tuple(hint_events),
                "hints",
            ),
            self._fact(
                "player.dialogue_loops",
                metrics.dialogue_loops,
                tuple(dialogue_loop_events),
                "loops",
            ),
            self._fact(
                "player.inaccessible_paths",
                metrics.inaccessible_paths,
                tuple(inaccessible_events),
                "paths",
            ),
            self._fact(
                "player.narrative_contradictions",
                metrics.narrative_contradictions,
                tuple(contradiction_events),
                "contradictions",
            ),
            self._fact(
                "player.clues_discovered",
                metrics.clues_discovered,
                tuple(clue_events),
                "clues",
            ),
            self._fact(
                "player.quest_comprehended",
                metrics.quest_comprehended,
                tuple(comprehension_events),
            ),
            *tuple(
                self._fact(
                    "player.invalid_action_reason",
                    reason,
                    (event_id,),
                )
                for reason in sorted(invalid_reasons)
                for event_id in invalid_evidence_by_reason[reason]
            ),
        )
        return PlayerEvaluationResult(metrics=metrics, facts=facts)

    def as_verifier(
        self,
        events: tuple[EventEnvelopeV2, ...],
        final_state: dict[str, Any],
    ) -> tuple[VerifierFact, ...]:
        return self.verify(events, final_state).facts

    def _fact(
        self,
        fact_type: str,
        value: bool | int | float | str,
        evidence: tuple[uuid.UUID, ...] = (),
        unit: str | None = None,
    ) -> VerifierFact:
        return VerifierFact(
            fact_type=fact_type,
            value=value,
            unit=unit,
            evidence_event_ids=evidence,
            verifier_version=self.VERSION,
        )

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from statistics import mean

from cognition.policy import ActionOption, UtilityPolicy
from domains.tabletop.onboarding import (
    EXPECTED_ACTION,
    ONBOARDING_STEPS,
    command_definition,
)
from experiments.models import CohortReport, TrialOutput
from experiments.player_evaluation import PlayerEvaluationVerifier
from kernel.command_bus import CommandBus
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal, VerifierFact
from kernel.state import BranchState, InMemoryStateStore
from persona.compilation import PersonaCompiler
from persona.generation import PersonaGenerator
from persona.models import CompiledPersona, PersonaBlueprint
from persona.registry import PersonaSchemaRegistry


def _id(label: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"tabletop-dm:{label}")


def _decision_seed(seed: int, persona_id: uuid.UUID, step: int, attempt: int) -> int:
    digest = hashlib.sha256(f"{seed}:{persona_id}:{step}:{attempt}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


class OnboardingExperiment:
    SCENARIO_ID = "player-onboarding"
    VERSION = "1.0.0"
    VERIFIER_VERSION = "onboarding-verifier-1.0.0"

    def __init__(self) -> None:
        self.registry = PersonaSchemaRegistry.load_default()
        self.generator = PersonaGenerator(self.registry)
        self.compiler = PersonaCompiler()
        self.policy = UtilityPolicy()
        self.player_verifier = PlayerEvaluationVerifier()

    def run_cohort(
        self,
        cohort_size: int = 12,
        seeds: tuple[int, ...] = (101, 202, 303),
        include_trials: int = 6,
        on_trial: Callable[[int, int, TrialOutput], None] | None = None,
    ) -> CohortReport:
        if cohort_size < 1 or cohort_size > 10_000:
            raise ValueError("cohort_size must be between 1 and 10000")
        if not seeds:
            raise ValueError("At least one seed is required")
        trials: list[TrialOutput] = []
        total = cohort_size * len(seeds)
        for seed in seeds:
            for index in range(cohort_size):
                persona_seed = seed * 100_000 + index
                persona = self.generator.generate(persona_seed)
                trial = self.run_trial(persona, seed)
                trials.append(trial)
                if on_trial is not None:
                    on_trial(len(trials), total, trial)

        completed = sum(bool(trial.metrics["completed"]) for trial in trials)

        def numeric(name: str) -> float:
            return mean(float(trial.metrics[name]) for trial in trials)

        return CohortReport(
            scenario_id=self.SCENARIO_ID,
            scenario_version=self.VERSION,
            trial_count=len(trials),
            completed=completed,
            completion_rate=round(completed / len(trials), 4),
            canonical_world_unchanged=all(
                trial.canonical_hash_before == trial.canonical_hash_after for trial in trials
            ),
            metrics={
                "mean_steps": round(numeric("steps"), 4),
                "mean_invalid_actions": round(numeric("invalid_actions"), 4),
                "mean_help_requests": round(numeric("help_requests"), 4),
                "mean_hints_requested": round(numeric("hints_requested"), 4),
                "mean_dialogue_loops": round(numeric("dialogue_loops"), 4),
                "comprehension_rate": round(numeric("comprehended_first_goal"), 4),
                "mean_time_to_first_valid_action": round(numeric("time_to_first_valid_action"), 4),
                "abandonment_rate": round(numeric("abandoned"), 4),
                "mean_deaths": round(numeric("deaths"), 4),
                "mean_inaccessible_paths": round(numeric("inaccessible_paths"), 4),
                "mean_narrative_contradictions": round(numeric("narrative_contradictions"), 4),
            },
            sample_trials=tuple(trials[: max(0, include_trials)]),
        )

    def run_trial(self, persona: PersonaBlueprint, seed: int) -> TrialOutput:
        compiled = self.compiler.compile(persona)
        world_id = _id("onboarding-world")
        canonical_branch_id = _id("onboarding-world:canonical")
        trial_id = _id(f"trial:{persona.persona_id}:{seed}")
        branch_id = _id(f"branch:{trial_id}")
        run_id = _id(f"run:{trial_id}")
        actor_id = _id(f"actor:{persona.persona_id}")
        entity_id = _id(f"entity:{persona.persona_id}")

        states = InMemoryStateStore()
        canonical = BranchState(
            world_id=world_id,
            branch_id=canonical_branch_id,
            kind=BranchKind.CANONICAL,
            projections={"tabletop.onboarding": {}},
        )
        states.add(canonical)
        trial = states.create_trial(canonical_branch_id, branch_id)
        canonical_before = canonical.state_hash
        bus = CommandBus(states)
        bus.register(command_definition())
        actor = Actor(
            actor_id=actor_id,
            kind=ActorKind.AGENT,
            display_name=f"Simulated player {str(persona.persona_id)[:8]}",
            roles=frozenset({"TEST_PERSONA", "PLAYER"}),
            capabilities=frozenset({"world.read", "action.propose", "entity.act"}),
            controlled_entity_ids=frozenset({entity_id}),
        )

        traces = []
        evidence = []
        events = []
        attempts_by_step: dict[int, int] = {}
        max_steps = 24
        for logical_step in range(max_steps):
            record = trial.projections.get("tabletop.onboarding", {}).get(
                str(entity_id),
                {
                    "step_index": 0,
                    "invalid_actions": 0,
                    "help_requests": 0,
                    "hints_requested": 0,
                    "dialogue_loops": 0,
                    "completed": False,
                    "had_help_this_step": False,
                },
            )
            if record["completed"]:
                break
            step_index = int(record["step_index"])
            attempts_by_step[step_index] = attempts_by_step.get(step_index, 0) + 1
            decision_seed = _decision_seed(
                seed, persona.persona_id, step_index, attempts_by_step[step_index]
            )
            options = self._options(compiled, step_index, bool(record["had_help_this_step"]))
            trace = self.policy.choose(compiled, decision_seed, options)
            traces.append(trace)
            proposal = CommandProposal(
                command_id=_id(f"command:{trial_id}:{logical_step}"),
                command_type="tabletop.onboarding.act",
                world_id=world_id,
                branch_id=branch_id,
                run_id=run_id,
                actor_id=actor_id,
                embodied_entity_id=entity_id,
                parameters={"action": trace.chosen_action},
                idempotency_key=f"{trial_id}:{logical_step}",
                correlation_id=trial_id,
                seed=decision_seed,
            )
            receipt = bus.execute(proposal, actor)
            evidence.append(receipt.event.event_id)
            events.append(
                receipt.event.model_copy(
                    update={
                        "created_at": datetime(2000, 1, 1, tzinfo=UTC)
                        + timedelta(microseconds=receipt.event.event_id.int % 86_400_000_000)
                    }
                )
            )

        record = trial.projections["tabletop.onboarding"][str(entity_id)]
        completed = bool(record["completed"])
        comprehended = completed and int(record["invalid_actions"]) <= 2
        canonical_after = canonical.state_hash
        player_evaluation = self.player_verifier.verify(
            tuple(events),
            {
                **record,
                "abandoned": not completed,
                "deaths": int(record.get("deaths", 0)),
                "inaccessible_paths": int(record.get("inaccessible_paths", 0)),
                "narrative_contradictions": int(record.get("narrative_contradictions", 0)),
                "quest_comprehended": comprehended,
            },
        )
        facts = (
            VerifierFact(
                fact_type="onboarding.completed",
                value=completed,
                evidence_event_ids=tuple(evidence),
                verifier_version=self.VERIFIER_VERSION,
            ),
            VerifierFact(
                fact_type="onboarding.invalid_action_count",
                value=int(record["invalid_actions"]),
                unit="actions",
                evidence_event_ids=tuple(evidence),
                verifier_version=self.VERIFIER_VERSION,
            ),
            VerifierFact(
                fact_type="kernel.canonical_world_unchanged",
                value=canonical_before == canonical_after,
                verifier_version="branch-isolation-verifier-1.0.0",
            ),
            *player_evaluation.facts,
        )
        return TrialOutput(
            trial_id=trial_id,
            persona_id=persona.persona_id,
            seed=seed,
            status="COMPLETED" if completed else "HORIZON_REACHED",
            steps=len(traces),
            canonical_hash_before=canonical_before,
            canonical_hash_after=canonical_after,
            trial_state_hash=trial.state_hash,
            traces=tuple(traces),
            events=tuple(events),
            facts=facts,
            metrics={
                "completed": completed,
                "steps": len(traces),
                "invalid_actions": int(record["invalid_actions"]),
                "help_requests": int(record["help_requests"]),
                "hints_requested": int(record["hints_requested"]),
                "dialogue_loops": int(record["dialogue_loops"]),
                "comprehended_first_goal": comprehended,
                **player_evaluation.metrics.model_dump(),
            },
        )

    @staticmethod
    def _options(
        persona: CompiledPersona, step_index: int, had_help: bool
    ) -> tuple[ActionOption, ...]:
        weights = persona.policy_weights
        step = ONBOARDING_STEPS[min(step_index, len(ONBOARDING_STEPS) - 1)]
        expected = EXPECTED_ACTION[step]
        valid_score = 0.35 + 0.35 * weights["rules_familiarity"] + 0.2 * weights["patience"]
        if step == "LEARN_CONTROLS":
            valid_score += 0.25 * weights["reading_tolerance"]
        if step in {"COMPLETE_TASK", "CHOOSE_PATH"}:
            valid_score += 0.2 * weights["curiosity"]
        if had_help:
            valid_score += 0.55
        invalid_score = 0.55 - 0.3 * weights["rules_familiarity"] - 0.2 * weights["patience"]
        options = [
            ActionOption(expected, {"goal_alignment": valid_score, "habit": 0.1}),
            ActionOption("INVALID_ACTION", {"uncertainty": invalid_score, "moral_cost": -0.1}),
        ]
        if step in {"LEARN_CONTROLS", "COMPLETE_TASK"} and not had_help:
            options.append(
                ActionOption(
                    "ASK_HELP",
                    {
                        "help_seeking": 0.25 + 0.55 * weights["help_seeking"],
                        "uncertainty_relief": 0.25 * (1 - weights["rules_familiarity"]),
                    },
                )
            )
        return tuple(options)

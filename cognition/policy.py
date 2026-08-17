from __future__ import annotations

import random
import uuid
from dataclasses import dataclass

from kernel.contracts import DecisionCandidate, DecisionTrace
from persona.models import CompiledPersona


@dataclass(frozen=True)
class ActionOption:
    action: str
    factors: dict[str, float]


class UtilityPolicy:
    VERSION = "onboarding-policy-1.0.0"

    def choose(
        self,
        persona: CompiledPersona,
        seed: int,
        options: tuple[ActionOption, ...],
    ) -> DecisionTrace:
        rng = random.Random(seed)
        candidates: list[DecisionCandidate] = []
        for option in sorted(options, key=lambda item: item.action):
            score = sum(option.factors.values()) + rng.uniform(-0.05, 0.05)
            candidates.append(
                DecisionCandidate(
                    action=option.action,
                    score=round(score, 6),
                    factors=option.factors,
                )
            )
        chosen = max(candidates, key=lambda candidate: (candidate.score, candidate.action))
        trace_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"tabletop-dm:trace:{persona.persona_id}:{self.VERSION}:{seed}:{chosen.action}",
        )
        return DecisionTrace(
            trace_id=trace_id,
            persona_id=persona.persona_id,
            persona_version=persona.persona_version,
            policy_version=self.VERSION,
            runtime_kind="UTILITY",
            seed=seed,
            candidates=tuple(candidates),
            chosen_action=chosen.action,
        )

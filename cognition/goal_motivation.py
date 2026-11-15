"""Bounded goal preferences from pinned identity and validated subjective evidence."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cognition.beliefs import BeliefClaim
from kernel.state import stable_hash
from persona.models import CompiledPersona, PersonaPurpose

if TYPE_CHECKING:
    from cognition.context import CharacterContext
    from domains.tabletop.character_bindings import CharacterBinding

POLICY_VERSION = "npc-goal-motivation-1.0.0"
MOTIVE_TRAITS = {
    "DUTY": ("conscientiousness", "achievement_priority"),
    "CURIOSITY": ("curiosity", "openness"),
    "CARE": ("agreeableness", "community_loyalty"),
    "RECOVERY": ("security_priority", "patience"),
}
LEVEL = {"LOW": -20, "MEDIUM": 0, "HIGH": 20}


class GoalMotivation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: uuid.UUID
    world_id: uuid.UUID
    branch_id: uuid.UUID
    run_id: uuid.UUID
    entity_id: uuid.UUID
    persona_version: str
    compiler_version: str
    policy_version: str = POLICY_VERSION
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0, le=(1 << 63) - 1)
    priorities: dict[str, int]
    avoided: tuple[str, ...] = ()
    unsafe_places: tuple[dict, ...] = ()
    source_event_ids: tuple[uuid.UUID, ...] = ()
    belief_ids: tuple[uuid.UUID, ...] = ()


def motive(goal: dict) -> str:
    return goal.get("motive") or ("DUTY" if goal["kind"] == "WEED" else "RECOVERY")


def derive_motivation(
    context: CharacterContext,
    binding: CharacterBinding,
    profile: CompiledPersona,
    goals: list[dict],
    home: dict,
    run_seed: int | None,
) -> GoalMotivation:
    from population.life import Place

    if profile.purpose is not PersonaPurpose.CHARACTER or (
        profile.persona_id,
        profile.persona_version,
        profile.compiler_version,
    ) != (binding.persona_id, str(binding.persona_version_id), binding.compiler_version):
        raise ValueError("NPC goals require the pinned CHARACTER persona")
    if (context.scene.world_id, context.scene.branch_id, context.scene.observer_entity_id) != (
        binding.world_id,
        binding.branch_id,
        binding.entity_id,
    ):
        raise ValueError("goal context does not belong to this binding")
    observations = {row.observation_id: row for row in context.observations}
    order: dict[uuid.UUID | None, int] = {
        row.observation_id: index for index, row in enumerate(context.observations)
    }
    places = {stable_hash(goal["place"]) for goal in goals} | {stable_hash(home)}
    motives = {motive(goal) for goal in goals}
    claims: list[dict] = []
    danger: dict[str, tuple[int, int, str, dict, bool]] = {}
    importance: dict[str, tuple[int, int, str, int]] = {}
    for belief in sorted(
        context.beliefs,
        key=lambda row: (order.get(row.source_observation_id, -1), str(row.belief_id)),
    ):
        source = (
            observations.get(belief.source_observation_id) if belief.source_observation_id else None
        )
        if (
            source is None
            or belief.entity_id != binding.entity_id
            or belief.contradicted_by_event_id
        ):
            continue
        try:
            claim_confidences = [
                claim.confidence
                for raw in source.perceived_payload.get("claims", ())
                if (claim := BeliefClaim.model_validate(raw)).subject_type == belief.subject_type
                and claim.subject_id == belief.subject_id
                and claim.predicate == belief.predicate
                and stable_hash(claim.value) == stable_hash(belief.value)
            ]
        except (ValidationError, TypeError):
            continue
        if not claim_confidences:
            continue
        confidence = round(min(belief.confidence, source.confidence, max(claim_confidences)) * 1000)
        if confidence <= 0 or not isinstance(belief.value, dict):
            continue
        rank = (confidence, order[source.observation_id], str(belief.belief_id))
        value = belief.value
        if belief.predicate == "place_danger" and belief.subject_type == "place":
            if set(value) != {"place", "dangerous"} or type(value["dangerous"]) is not bool:
                continue
            try:
                place = Place.model_validate(value["place"]).model_dump(mode="json")
            except (ValidationError, TypeError):
                continue
            key = stable_hash(place)
            if key not in places:
                continue
            if key not in danger or rank > danger[key][:3]:
                danger[key] = (*rank, place, value["dangerous"])
        elif (
            belief.predicate == "motive_importance"
            and belief.subject_type == "entity"
            and belief.subject_id == binding.entity_id
        ):
            if (
                set(value) != {"motive", "importance"}
                or not isinstance(value["motive"], str)
                or value["motive"] not in motives
                or type(value["importance"]) is not int
                or not -100 <= value["importance"] <= 100
            ):
                continue
            key = value["motive"]
            if key not in importance or rank > importance[key][:3]:
                importance[key] = (*rank, value["importance"])
        else:
            continue
        claims.append(
            {
                "belief_id": str(belief.belief_id),
                "event": str(source.source_event_id),
                "predicate": belief.predicate,
                "value": value,
                "confidence": confidence,
            }
        )
    threshold = {"LOW": 250, "MEDIUM": 500, "HIGH": 750}.get(
        str(profile.deep_traits.get("risk_tolerance")), 500
    )
    unsafe = tuple(row[3] for _, row in sorted(danger.items()) if row[4] and row[0] >= threshold)
    priorities = {}
    for goal in goals:
        category = motive(goal)
        temperament = sum(
            LEVEL.get(str(profile.deep_traits.get(trait)), 0) for trait in MOTIVE_TRAITS[category]
        )
        conviction = importance.get(category)
        priorities[goal["goal_id"]] = (
            goal["priority"]
            + temperament
            + (conviction[3] * conviction[0] // 1000 if conviction else 0)
        )
    inputs = {
        "policy": POLICY_VERSION,
        "binding": binding.model_dump(mode="json", exclude={"recorded_at", "recorded_by"}),
        "traits": {
            trait: profile.deep_traits.get(trait)
            for trait in sorted(
                {"risk_tolerance"} | {name for names in MOTIVE_TRAITS.values() for name in names}
            )
        },
        "goals": goals,
        "home": home,
        "beliefs": claims,
        "run_seed": run_seed or 0,
    }
    digest = stable_hash(inputs)
    return GoalMotivation(
        binding_id=binding.binding_id,
        world_id=binding.world_id,
        branch_id=binding.branch_id,
        run_id=binding.run_id,
        entity_id=binding.entity_id,
        persona_version=profile.persona_version,
        compiler_version=profile.compiler_version,
        input_hash=digest,
        seed=int(digest[:16], 16) & ((1 << 63) - 1),
        priorities=priorities,
        avoided=tuple(sorted(goal["goal_id"] for goal in goals if goal["place"] in unsafe)),
        unsafe_places=unsafe,
        source_event_ids=tuple(sorted({uuid.UUID(row["event"]) for row in claims}, key=str)),
        belief_ids=tuple(sorted({uuid.UUID(row["belief_id"]) for row in claims}, key=str)),
    )

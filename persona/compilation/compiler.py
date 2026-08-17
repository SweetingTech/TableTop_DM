from __future__ import annotations

import math

from persona.models import CompiledPersona, PersonaBlueprint, PromptAssembly
from persona.versioning import PersonaVersioning

LEVEL = {"LOW": 0.25, "MEDIUM": 0.55, "HIGH": 0.85}


class PersonaCompiler:
    VERSION = "persona-compiler-0.2.0"

    def compile(
        self,
        persona: PersonaBlueprint,
        *,
        persona_version: str | None = None,
    ) -> CompiledPersona:
        dims = persona.dimensions
        risk = LEVEL.get(str(dims.get("risk_tolerance")), 0.55)
        patience = LEVEL.get(str(dims.get("patience")), 0.55)
        curiosity = LEVEL.get(str(dims.get("curiosity")), 0.55)
        reading = LEVEL.get(str(dims.get("reading_tolerance")), 0.55)
        help_willingness = LEVEL.get(str(dims.get("help_seeking")), 0.55)
        familiarity = {"NONE": 0.05, "LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.9}.get(
            str(dims.get("rules_familiarity")), 0.3
        )
        style = str(dims.get("player_style", "BALANCED")).lower().replace("_", " ")
        experience = str(dims.get("rules_familiarity", "MEDIUM")).lower()
        return CompiledPersona(
            persona_id=persona.persona_id,
            persona_version=persona_version or str(PersonaVersioning.record(persona).version_id),
            compiler_version=self.VERSION,
            identity_summary=(
                f"A {style} player with {experience} rules familiarity, "
                f"{dims.get('risk_tolerance', 'MEDIUM').lower()} risk tolerance, and "
                f"{dims.get('reading_tolerance', 'MEDIUM').lower()} reading tolerance."
            ),
            policy_weights={
                "risk_penalty": round(1.8 - risk, 4),
                "patience": patience,
                "curiosity": curiosity,
                "reading_tolerance": reading,
                "help_seeking": help_willingness,
                "rules_familiarity": familiarity,
                "invalid_action_penalty": 1.25,
            },
            starting_goals=(
                "understand_controls",
                "complete_first_goal",
                "finish_onboarding",
            ),
            retrieval_filters=(
                "onboarding",
                "rules",
                f"style:{style.replace(' ', '_')}",
            ),
            starting_beliefs=(
                {
                    "subject_type": "self",
                    "predicate": "risk_tolerance",
                    "value": dims.get("risk_tolerance", "MEDIUM"),
                    "confidence": 1.0,
                },
                {
                    "subject_type": "self",
                    "predicate": "authority_trust",
                    "value": dims.get("authority_trust", "MEDIUM"),
                    "confidence": 1.0,
                },
            ),
            starting_relationships=(
                {
                    "target_role": "GM",
                    "trust": round(
                        (LEVEL.get(str(dims.get("dm_trust")), 0.55) - 0.5) * 40,
                        4,
                    ),
                    "familiarity": round(familiarity * 20, 4),
                },
            ),
            routines=(
                {
                    "routine": "review_available_actions",
                    "frequency": "EACH_INTERACTION",
                    "priority": round(0.4 + 0.5 * patience, 4),
                },
                {
                    "routine": "seek_help_when_blocked",
                    "frequency": "ON_FAILURE",
                    "priority": help_willingness,
                },
            ),
            capability_modifiers={
                "rules.interpret": familiarity,
                "interface.navigate": {
                    "NONE": 0.1,
                    "LOW": 0.35,
                    "MEDIUM": 0.65,
                    "HIGH": 0.9,
                }.get(str(dims.get("interface_familiarity")), 0.35),
                "text.process": reading,
                "plan.persist": patience,
            },
            deep_traits=dict(sorted(dims.items())),
        )

    @staticmethod
    def assemble_prompt(
        persona: CompiledPersona,
        *,
        situation_summary: str = "",
        relevant_traits: tuple[str, ...] = (),
        max_tokens: int = 800,
        max_characters: int = 3_200,
    ) -> PromptAssembly:
        if max_tokens < 1 or max_characters < 1:
            raise ValueError("Prompt budgets must be positive")
        selected = tuple(
            name for name in sorted(set(relevant_traits)) if name in persona.deep_traits
        )
        sections = [f"Identity: {persona.identity_summary}"]
        if situation_summary.strip():
            sections.append(f"Situation: {situation_summary.strip()}")
        if selected:
            traits = ", ".join(f"{name}={persona.deep_traits[name]}" for name in selected)
            sections.append(f"Relevant traits: {traits}")
        sections.append(f"Active goals: {', '.join(persona.starting_goals)}")
        text = "\n".join(sections)
        effective_limit = min(max_characters, max_tokens * 4)
        truncated = len(text) > effective_limit
        if truncated:
            text = text[:effective_limit]
            if " " in text and effective_limit > 16:
                text = text.rsplit(" ", 1)[0]
            text = text.rstrip()
        return PromptAssembly(
            text=text,
            estimated_tokens=max(1, math.ceil(len(text) / 4)),
            character_count=len(text),
            max_tokens=max_tokens,
            max_characters=max_characters,
            included_traits=selected,
            truncated=truncated,
        )

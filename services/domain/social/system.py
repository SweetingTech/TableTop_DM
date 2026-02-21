import uuid
from shared.schemas.enums import TensionLevel, TENSION_LADDER
from shared.schemas.events import StateDelta, ToolCallPayload
from shared.db.connection import execute_one
from services.mechanics.dice import roll_d20


class SocialSystem:
    def get_tension(
        self, campaign_id: uuid.UUID, entity_a: uuid.UUID, entity_b: uuid.UUID
    ) -> TensionLevel:
        row = execute_one(
            """
            SELECT payload->>'tension_level' as tension
            FROM state.intents
            WHERE campaign_id = %s AND entity_id = %s
            AND payload->>'target_entity_id' = %s
            ORDER BY created_at DESC LIMIT 1
        """,
            (str(campaign_id), str(entity_a), str(entity_b)),
        )

        if row and row.get("tension"):
            try:
                return TensionLevel(row["tension"])
            except ValueError:
                pass
        return TensionLevel.CALM

    def escalate_tension(
        self,
        campaign_id: uuid.UUID,
        entity_a: uuid.UUID,
        entity_b: uuid.UUID,
        current: TensionLevel,
    ) -> dict:
        idx = TENSION_LADDER.index(current)
        if idx >= len(TENSION_LADDER) - 1:
            return {
                "success": False,
                "reason": "Already at maximum tension (COMBAT)",
                "current": current.value,
            }

        new_level = TENSION_LADDER[idx + 1]
        return {
            "success": True,
            "previous": current.value,
            "new": new_level.value,
            "triggers_combat": new_level == TensionLevel.COMBAT,
        }

    def deescalate_tension(
        self,
        campaign_id: uuid.UUID,
        entity_a: uuid.UUID,
        entity_b: uuid.UUID,
        current: TensionLevel,
    ) -> dict:
        idx = TENSION_LADDER.index(current)
        if idx <= 0:
            return {
                "success": False,
                "reason": "Already at minimum tension (CALM)",
                "current": current.value,
            }

        new_level = TENSION_LADDER[idx - 1]
        return {
            "success": True,
            "previous": current.value,
            "new": new_level.value,
        }

    def resolve_social_check(
        self, entity_id: uuid.UUID, skill: str, modifier: int, dc: int
    ) -> ToolCallPayload:
        roll = roll_d20(modifier)
        success = roll.total >= dc

        return ToolCallPayload(
            tool_name="social_check",
            arguments={"entity_id": str(entity_id), "skill": skill, "dc": dc},
            result={
                "entity_id": str(entity_id),
                "skill": skill,
                "roll": roll.total,
                "dc": dc,
                "success": success,
            },
            rolls=[roll],
            deltas=[],
        )


class AmbushPipeline:
    def resolve_stealth(
        self, ambusher_id: uuid.UUID, stealth_mod: int, targets: list[dict]
    ) -> dict:
        stealth_roll = roll_d20(stealth_mod)

        surprised = []
        aware = []

        for target in targets:
            perception_mod = target.get("perception_modifier", 0)
            perception_roll = roll_d20(perception_mod)

            if stealth_roll.total > perception_roll.total:
                surprised.append(
                    {
                        "entity_id": str(target["entity_id"]),
                        "name": target.get("name", "Unknown"),
                        "perception_roll": perception_roll.total,
                    }
                )
            else:
                aware.append(
                    {
                        "entity_id": str(target["entity_id"]),
                        "name": target.get("name", "Unknown"),
                        "perception_roll": perception_roll.total,
                    }
                )

        return {
            "ambusher_id": str(ambusher_id),
            "stealth_roll": stealth_roll.total,
            "surprised": surprised,
            "aware": aware,
            "full_surprise": len(aware) == 0,
        }

    def apply_surprise(
        self, ambush_result: dict, encounter_id: uuid.UUID, conn=None
    ) -> list[StateDelta]:
        deltas = []
        for target in ambush_result.get("surprised", []):
            deltas.append(
                StateDelta(
                    table="state.conditions",
                    operation="INSERT",
                    entity_id=uuid.UUID(target["entity_id"]),
                    changes={
                        "condition_type": "SURPRISED",
                        "duration_rounds": 1,
                        "source": "ambush",
                        "encounter_id": str(encounter_id),
                    },
                    domain_tags=["surprise", "ambush", "combat"],
                )
            )
        return deltas

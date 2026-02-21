import uuid
from typing import Optional
from shared.schemas.events import StateDelta, ToolCallPayload
from services.mechanics.dice import roll_dice, roll_d20


class MechanicsEngine:
    def update_hp(
        self,
        entity_id: uuid.UUID,
        delta: int,
        current_hp: int,
        max_hp: int,
        source: str = "unknown",
    ) -> ToolCallPayload:
        new_hp = max(0, min(max_hp, current_hp + delta))
        deltas = [
            StateDelta(
                table="state.entities",
                operation="UPDATE",
                entity_id=entity_id,
                changes={"hp_current": new_hp, "hp_previous": current_hp},
                domain_tags=["damage" if delta < 0 else "healing"],
            )
        ]
        result = {
            "entity_id": str(entity_id),
            "hp_previous": current_hp,
            "hp_current": new_hp,
            "delta": delta,
            "source": source,
            "is_down": new_hp == 0,
        }
        return ToolCallPayload(
            tool_name="update_hp",
            arguments={"entity_id": str(entity_id), "delta": delta, "source": source},
            result=result,
            deltas=deltas,
        )

    def apply_condition(
        self,
        entity_id: uuid.UUID,
        condition: str,
        duration_rounds: int = -1,
        source: str = "unknown",
        campaign_id: uuid.UUID = None,
        encounter_id: uuid.UUID = None,
    ) -> ToolCallPayload:
        deltas = [
            StateDelta(
                table="state.conditions",
                operation="INSERT",
                entity_id=entity_id,
                changes={
                    "condition_type": condition,
                    "duration_rounds": duration_rounds,
                    "source": source,
                    "campaign_id": str(campaign_id) if campaign_id else None,
                    "encounter_id": str(encounter_id) if encounter_id else None,
                },
                domain_tags=["condition_applied", condition.lower()],
            )
        ]
        return ToolCallPayload(
            tool_name="apply_condition",
            arguments={
                "entity_id": str(entity_id),
                "condition": condition,
                "duration_rounds": duration_rounds,
                "source": source,
            },
            result={"applied": condition, "entity_id": str(entity_id)},
            deltas=deltas,
        )

    def remove_condition(self, entity_id: uuid.UUID, condition: str) -> ToolCallPayload:
        deltas = [
            StateDelta(
                table="state.conditions",
                operation="DELETE",
                entity_id=entity_id,
                changes={"condition_type": condition},
                domain_tags=["condition_removed", condition.lower()],
            )
        ]
        return ToolCallPayload(
            tool_name="remove_condition",
            arguments={"entity_id": str(entity_id), "condition": condition},
            result={"removed": condition, "entity_id": str(entity_id)},
            deltas=deltas,
        )

    def modify_inventory(
        self, entity_id: uuid.UUID, item_id: uuid.UUID, quantity_delta: int
    ) -> ToolCallPayload:
        op = "UPDATE" if quantity_delta != 0 else "DELETE"
        domain_tag = "item_gained" if quantity_delta > 0 else "item_lost"
        deltas = [
            StateDelta(
                table="state.entities",
                operation=op,
                entity_id=entity_id,
                changes={"item_id": str(item_id), "quantity_delta": quantity_delta},
                domain_tags=[domain_tag],
            )
        ]
        return ToolCallPayload(
            tool_name="modify_inventory",
            arguments={
                "entity_id": str(entity_id),
                "item_id": str(item_id),
                "quantity_delta": quantity_delta,
            },
            result={
                "entity_id": str(entity_id),
                "item_id": str(item_id),
                "quantity_delta": quantity_delta,
            },
            deltas=deltas,
        )

    def resolve_attack(
        self,
        attacker_id: uuid.UUID,
        target_id: uuid.UUID,
        attack_modifier: int,
        target_ac: int,
        damage_dice: str,
        damage_modifier: int = 0,
        weapon: str = "unarmed",
        attacker_hp: int = 0,
        attacker_max_hp: int = 0,
        target_hp: int = 0,
        target_max_hp: int = 0,
    ) -> ToolCallPayload:
        attack_roll = roll_d20(attack_modifier)
        hits = attack_roll.total >= target_ac
        natural_20 = attack_roll.rolls[0] == 20
        natural_1 = attack_roll.rolls[0] == 1

        if natural_1:
            hits = False
        elif natural_20:
            hits = True

        rolls = [attack_roll]
        deltas = []
        damage_total = 0

        if hits:
            damage_roll = roll_dice(damage_dice, damage_modifier)
            if natural_20:
                crit_roll = roll_dice(damage_dice, 0)
                damage_total = damage_roll.total + crit_roll.total
                rolls.extend([damage_roll, crit_roll])
            else:
                damage_total = damage_roll.total
                rolls.append(damage_roll)

            new_hp = max(0, target_hp - damage_total)
            deltas.append(
                StateDelta(
                    table="state.entities",
                    operation="UPDATE",
                    entity_id=target_id,
                    changes={"hp_current": new_hp, "hp_previous": target_hp},
                    domain_tags=["damage", "combat", "attack"],
                )
            )

        result = {
            "attacker_id": str(attacker_id),
            "target_id": str(target_id),
            "weapon": weapon,
            "attack_roll": attack_roll.total,
            "target_ac": target_ac,
            "hits": hits,
            "natural_20": natural_20,
            "natural_1": natural_1,
            "damage": damage_total,
            "target_down": hits and (target_hp - damage_total) <= 0,
        }

        return ToolCallPayload(
            tool_name="resolve_attack",
            arguments={
                "attacker_id": str(attacker_id),
                "target_id": str(target_id),
                "weapon": weapon,
                "damage_dice": damage_dice,
            },
            result=result,
            deltas=deltas,
            rolls=rolls,
        )

    def resolve_save(
        self,
        entity_id: uuid.UUID,
        save_modifier: int,
        dc: int,
        save_type: str = "DEX",
        effect_on_fail: Optional[str] = None,
        damage_dice: Optional[str] = None,
        half_on_save: bool = False,
        entity_hp: int = 0,
        entity_max_hp: int = 0,
    ) -> ToolCallPayload:
        save_roll = roll_d20(save_modifier)
        success = save_roll.total >= dc
        rolls = [save_roll]
        deltas = []
        damage_total = 0

        if damage_dice:
            damage_roll = roll_dice(damage_dice)
            rolls.append(damage_roll)

            if success and half_on_save:
                damage_total = damage_roll.total // 2
            elif not success:
                damage_total = damage_roll.total

            if damage_total > 0:
                new_hp = max(0, entity_hp - damage_total)
                deltas.append(
                    StateDelta(
                        table="state.entities",
                        operation="UPDATE",
                        entity_id=entity_id,
                        changes={"hp_current": new_hp, "hp_previous": entity_hp},
                        domain_tags=["damage", "save"],
                    )
                )

        if not success and effect_on_fail:
            deltas.append(
                StateDelta(
                    table="state.conditions",
                    operation="INSERT",
                    entity_id=entity_id,
                    changes={"condition_type": effect_on_fail, "source": "save_fail"},
                    domain_tags=["condition_applied", "save"],
                )
            )

        result = {
            "entity_id": str(entity_id),
            "save_type": save_type,
            "dc": dc,
            "roll": save_roll.total,
            "success": success,
            "damage": damage_total,
        }

        return ToolCallPayload(
            tool_name="resolve_save",
            arguments={"entity_id": str(entity_id), "save_type": save_type, "dc": dc},
            result=result,
            deltas=deltas,
            rolls=rolls,
        )

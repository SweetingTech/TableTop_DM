"""
NPC Autonomy - AI turn processing for AI-controlled entities.

When an AI_NPC entity's turn comes up in combat, this module decides
and executes their action without human intervention.
"""
import random
import uuid
from typing import Optional
from services.orchestrator.state_machine import StateMachine
from services.orchestrator.pipeline import OrchestratorPipeline
from shared.schemas.contracts import InterventionProposal
from shared.schemas.enums import GameMode
from shared.auth.principal import load_principal
from shared.db.connection import execute_one, execute_query


def maybe_trigger_combat(
    campaign_id: uuid.UUID,
    *,
    hostility_radius: int = 4,
    rng: Optional[random.Random] = None,
) -> bool:
    """AI-DM heuristic: switch a campaign to COMBAT mode when a hostile NPC
    is within ``hostility_radius`` tiles of any PC.

    Returns True if it flipped the mode. No-op if the campaign is already
    in COMBAT or if no hostile pair is in range.

    Used by the orchestrator when running in AI-DM mode (no human GM). The
    Control Plane "Enter Combat" button is the human-driven equivalent and
    just hits ``/api/campaigns/<id>/mode`` directly.
    """
    rng = rng or random.Random()
    sm = StateMachine()
    if sm.get_campaign_mode(campaign_id) == GameMode.COMBAT:
        return False

    rows = execute_query(
        "SELECT id, entity_type, public_sheet, tags FROM state.entities "
        "WHERE campaign_id = %s AND status = 'ACTIVE'",
        (str(campaign_id),),
    )
    pcs = [r for r in rows if r["entity_type"] == "PC"]
    hostiles = [
        r for r in rows
        if r["entity_type"] in ("NPC", "MONSTER")
        and (r.get("tags") or [])
        and any(t in ("enemy", "hostile", "monster") for t in (r.get("tags") or []))
    ]
    if not pcs or not hostiles:
        return False

    def pos(e):
        s = e.get("public_sheet") or {}
        return s.get("x"), s.get("y")

    for h in hostiles:
        hx, hy = pos(h)
        if hx is None or hy is None:
            continue
        for p in pcs:
            px, py = pos(p)
            if px is None or py is None:
                continue
            if max(abs(hx - px), abs(hy - py)) <= hostility_radius:
                # Tiny RNG bias so two near-misses in a row aren't both 100% triggers
                # (lets the AI-DM occasionally let the party slip past).
                if rng.random() < 0.85:
                    sm.set_campaign_mode(campaign_id, GameMode.COMBAT)
                    return True
    return False


class NPCAutonomy:
    """Handles autonomous decision-making for AI-controlled NPCs."""

    def __init__(self):
        self.state_machine = StateMachine()
        self.pipeline = OrchestratorPipeline()

    def process_npc_turn(
        self,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        encounter_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> list[dict]:
        """
        Process an NPC's turn autonomously.

        Returns list of action results.
        """
        entity = execute_one(
            "SELECT * FROM state.entities WHERE id = %s",
            (str(entity_id),)
        )
        if not entity:
            return []

        # Only process AI-controlled entities
        if entity.get("controlled_by") not in ("AI", "AI_NPC"):
            return []

        principal_id = entity.get("controller_principal_id")
        if not principal_id:
            return []

        principal = load_principal(uuid.UUID(str(principal_id)), campaign_id)
        if not principal:
            return []

        # Get NPC AI directive from secret_sheet (optional)
        secret_sheet = entity.get("secret_sheet") or {}
        directive = secret_sheet.get("ai_directive", "Act defensively")

        # Decide what actions to take
        actions = self._decide_actions(
            entity=entity,
            campaign_id=campaign_id,
            encounter_id=encounter_id,
            directive=directive,
        )

        results = []
        for action in actions:
            proposal = InterventionProposal(
                action_type=action["type"],
                params=action["params"],
                proposer_principal_id=uuid.UUID(str(principal_id)),
                proposer_entity_id=entity_id,
                campaign_id=campaign_id,
                session_id=session_id,
                encounter_id=encounter_id,
            )

            try:
                result = self.pipeline.process_proposal(proposal, principal, session_id)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})

        # Always end turn after actions
        try:
            end_proposal = InterventionProposal(
                action_type="END_TURN",
                params={"entity_id": str(entity_id)},
                proposer_principal_id=uuid.UUID(str(principal_id)),
                campaign_id=campaign_id,
                session_id=session_id,
                encounter_id=encounter_id,
            )
            self.pipeline.process_proposal(end_proposal, principal, session_id)
        except Exception:
            pass

        return results

    def _decide_actions(
        self,
        entity: dict,
        campaign_id: uuid.UUID,
        encounter_id: uuid.UUID,
        directive: str,
    ) -> list[dict]:
        """
        Simple rule-based AI decision making.

        Currently implements:
        - Attack nearest enemy if in melee range (distance <= 1)
        - Move toward nearest enemy if not in range
        """
        actions = []

        # Get all participants in encounter
        slots = execute_query(
            """
            SELECT es.entity_id, e.name, e.tags, e.public_sheet, e.hp_current, e.entity_type
            FROM state.encounter_slots es
            JOIN state.entities e ON es.entity_id = e.id
            WHERE es.encounter_id = %s AND e.hp_current > 0
            """,
            (str(encounter_id),)
        )

        my_tags = set(entity.get("tags") or [])
        my_sheet = entity.get("public_sheet") or {}
        my_x = my_sheet.get("x", 0)
        my_y = my_sheet.get("y", 0)

        # Find enemies (PCs or entities tagged as party/hostile to us)
        enemies = []
        for slot in slots:
            if str(slot["entity_id"]) == str(entity["id"]):
                continue

            slot_tags = set(slot.get("tags") or [])
            slot_type = slot.get("entity_type", "")

            # Consider PCs as enemies for monsters/NPCs
            is_enemy = (
                slot_type == "PC" or
                "pc" in slot_tags or
                "party_alpha" in slot_tags or
                "party" in slot_tags
            )

            if is_enemy:
                slot_sheet = slot.get("public_sheet") or {}
                sx = slot_sheet.get("x", 0)
                sy = slot_sheet.get("y", 0)
                dist = abs(sx - my_x) + abs(sy - my_y)  # Manhattan distance
                enemies.append({
                    "entity": slot,
                    "distance": dist,
                    "x": sx,
                    "y": sy,
                })

        # Sort by distance
        enemies.sort(key=lambda x: x["distance"])

        if enemies:
            nearest = enemies[0]
            if nearest["distance"] <= 1:
                # In melee range - attack
                actions.append({
                    "type": "ATTACK",
                    "params": {
                        "attacker_id": str(entity["id"]),
                        "target_id": str(nearest["entity"]["entity_id"]),
                        "weapon": "melee",
                    }
                })
            else:
                # Move toward nearest enemy (one step closer)
                target_x = nearest["x"]
                target_y = nearest["y"]

                # Simple pathfinding: move one step closer
                dx = 0
                dy = 0
                if target_x > my_x:
                    dx = 1
                elif target_x < my_x:
                    dx = -1

                if target_y > my_y:
                    dy = 1
                elif target_y < my_y:
                    dy = -1

                # Move diagonally or straight
                new_x = my_x + dx
                new_y = my_y + dy

                actions.append({
                    "type": "MOVE",
                    "params": {
                        "entity_id": str(entity["id"]),
                        "destination_x": new_x,
                        "destination_y": new_y,
                    }
                })

        return actions

    def check_and_process_ai_turn(
        self,
        encounter_id: uuid.UUID,
        campaign_id: uuid.UUID,
        session_id: uuid.UUID,
        max_ai_turns: int = 3,
    ) -> list[dict]:
        """
        Check if current active entity is AI-controlled and process their turn.

        Returns list of results. Includes a safeguard to prevent infinite loops.
        """
        results = []
        turns_processed = 0

        while turns_processed < max_ai_turns:
            active_slot = self.state_machine.get_active_slot(encounter_id)
            if not active_slot:
                break

            entity_id = active_slot.get("entity_id")
            if not entity_id:
                break

            # Check if entity is AI-controlled
            entity = execute_one(
                "SELECT controlled_by FROM state.entities WHERE id = %s",
                (str(entity_id),)
            )

            if not entity or entity.get("controlled_by") not in ("AI", "AI_NPC"):
                # Not AI-controlled, stop processing
                break

            # Process AI turn
            turn_results = self.process_npc_turn(
                campaign_id=campaign_id,
                session_id=session_id,
                encounter_id=encounter_id,
                entity_id=uuid.UUID(str(entity_id)),
            )
            results.extend(turn_results)
            turns_processed += 1

        return results

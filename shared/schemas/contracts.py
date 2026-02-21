import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field

from shared.schemas.enums import PrincipalType


class InterventionProposal(BaseModel):
    proposal_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    action_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    proposer_principal_id: uuid.UUID
    proposer_entity_id: Optional[uuid.UUID] = None
    target_entity_id: Optional[uuid.UUID] = None
    campaign_id: uuid.UUID
    session_id: uuid.UUID
    encounter_id: Optional[uuid.UUID] = None
    idempotency_key: Optional[str] = None
    ap_cost: int = 0
    domain_tags: list[str] = Field(default_factory=list)


ACTION_REGISTRY = {
    "MOVE": {
        "params": ["entity_id", "destination_x", "destination_y"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "move_entity",
        "ap_cost": 1,
        "visibility": "party",
    },
    "ATTACK": {
        "params": ["attacker_id", "target_id", "weapon"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "resolve_attack",
        "ap_cost": 1,
        "visibility": "encounter",
    },
    "CAST_SPELL": {
        "params": ["caster_id", "spell_name", "target_id", "target_x", "target_y"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC, PrincipalType.AI_GOD],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "resolve_spell",
        "ap_cost": 1,
        "visibility": "encounter",
    },
    "USE_ITEM": {
        "params": ["user_id", "item_id", "target_id"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "modify_inventory",
        "ap_cost": 1,
        "visibility": "party",
    },
    "TALK": {
        "params": ["speaker_id", "target_id", "message"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "social_interaction",
        "ap_cost": 0,
        "visibility": "proximity",
    },
    "END_TURN": {
        "params": ["entity_id"],
        "proposers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.AI_NPC],
        "committers": [PrincipalType.HUMAN, PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "end_turn",
        "ap_cost": 0,
        "visibility": "encounter",
    },
    "OPPORTUNITY_ATTACK": {
        "params": ["attacker_id", "target_id", "weapon"],
        "proposers": [PrincipalType.SYSTEM],
        "committers": [PrincipalType.SYSTEM],
        "tool": "resolve_attack",
        "ap_cost": 0,
        "visibility": "encounter",
    },
    "DIVINE_BLESS": {
        "params": ["god_entity_id", "target_entity_id", "blessing_type", "magnitude"],
        "proposers": [PrincipalType.AI_GOD],
        "committers": [PrincipalType.SYSTEM],
        "tool": "apply_divine_effect",
        "ap_cost": 2,
        "visibility": "gods_only",
    },
    "DIVINE_CURSE": {
        "params": ["god_entity_id", "target_entity_id", "curse_type", "magnitude"],
        "proposers": [PrincipalType.AI_GOD],
        "committers": [PrincipalType.SYSTEM],
        "tool": "apply_divine_effect",
        "ap_cost": 3,
        "visibility": "gods_only",
    },
    "APPLY_CONDITION": {
        "params": ["entity_id", "condition", "duration_rounds", "source"],
        "proposers": [PrincipalType.SYSTEM, PrincipalType.AI_DM],
        "committers": [PrincipalType.SYSTEM],
        "tool": "apply_condition",
        "ap_cost": 0,
        "visibility": "encounter",
    },
    "REMOVE_CONDITION": {
        "params": ["entity_id", "condition"],
        "proposers": [PrincipalType.SYSTEM, PrincipalType.AI_DM],
        "committers": [PrincipalType.SYSTEM],
        "tool": "remove_condition",
        "ap_cost": 0,
        "visibility": "encounter",
    },
    "MODIFY_INVENTORY": {
        "params": ["entity_id", "item_id", "quantity_delta"],
        "proposers": [PrincipalType.SYSTEM, PrincipalType.AI_DM, PrincipalType.HUMAN],
        "committers": [PrincipalType.SYSTEM],
        "tool": "modify_inventory",
        "ap_cost": 0,
        "visibility": "party",
    },
    "SET_MODE": {
        "params": ["campaign_id", "new_mode"],
        "proposers": [PrincipalType.AI_DM],
        "committers": [PrincipalType.AI_DM, PrincipalType.SYSTEM],
        "tool": "set_game_mode",
        "ap_cost": 0,
        "visibility": "all",
    },
    "REVOKE_SPELL_ACCESS": {
        "params": ["entity_id", "spell_name", "reason"],
        "proposers": [PrincipalType.SYSTEM, PrincipalType.AI_GOD],
        "committers": [PrincipalType.SYSTEM],
        "tool": "revoke_spell",
        "ap_cost": 1,
        "visibility": "gods_only",
    },
    "SET_BOUNTY": {
        "params": ["target_entity_id", "amount", "faction_id", "reason"],
        "proposers": [PrincipalType.SYSTEM, PrincipalType.AI_DM],
        "committers": [PrincipalType.SYSTEM],
        "tool": "set_bounty",
        "ap_cost": 0,
        "visibility": "all",
    },
}


def validate_proposal(proposal: InterventionProposal, principal_type: PrincipalType) -> tuple[bool, str]:
    if proposal.action_type not in ACTION_REGISTRY:
        return False, f"Unknown action_type: {proposal.action_type}"

    entry = ACTION_REGISTRY[proposal.action_type]

    if principal_type not in entry["proposers"]:
        return False, f"{principal_type} cannot propose {proposal.action_type}"

    required_params = entry["params"]
    for p in required_params:
        if p not in proposal.params and p not in ("target_x", "target_y", "target_id", "message"):
            return False, f"Missing required param: {p}"

    return True, "valid"

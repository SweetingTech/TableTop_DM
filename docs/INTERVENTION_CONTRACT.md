# INTERVENTION_CONTRACT
Status: Phase 3.1 intervention contract registry specification.

## Registry rules
- Every `action_type` must exist in this registry.
- Unknown action types are hard-rejected during validation.
- Parameters are strict (`additionalProperties=false`) and versioned.
- Deterministic tool mapping is one-to-one from `action_type` to backend target.

## Authority model
- `who_can_propose`: principal roles allowed to submit intervention proposals.
- `who_can_commit`: only orchestrator service role after full validation pipeline.
- `authority_tier`: `1..5` where higher tiers can override lower tiers when override policy allows.

## Global policy hooks
- AP policy:
  - Per-event AP cost (`ap_cost`).
  - Encounter/session caps (`encounter_cap`, `session_cap`).
  - Daily/global cooldown gates (optional via `cooldown_key`).
- Stacking policy:
  - `STACK`: cumulative if `stack_limit` not exceeded.
  - `REPLACE`: replace prior active intervention in same `stack_group`.
  - `BLOCK`: reject if a conflicting intervention is active.
- Visibility defaults:
  - Defaults assigned at commit and may be widened only by explicit policy.

## Canonical registry entries (v1)

### 1) `BLESS_ATTACK`
- deterministic target: `mechanics.apply_modifier`
- who_can_propose: `AI_GOD`, `GM`
- who_can_commit: `SYSTEM`
- authority_tier: min 2
- stack_group: `attack_modifier:<target_entity_id>`
- stack_mode: `REPLACE`
- visibility_default: `GODS_ONLY`
- ap_cost: 2
- encounter_cap: 2
- session_cap: 8
- params schema:
```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["target_entity_id", "modifier", "duration_rounds"],
  "properties": {
    "target_entity_id": { "type": "string", "format": "uuid" },
    "modifier": { "type": "integer", "minimum": 1, "maximum": 5 },
    "duration_rounds": { "type": "integer", "minimum": 1, "maximum": 10 }
  }
}
```

### 2) `CURSE_DEFENSE`
- deterministic target: `mechanics.apply_modifier`
- who_can_propose: `AI_GOD`, `GM`
- who_can_commit: `SYSTEM`
- authority_tier: min 2
- stack_group: `defense_modifier:<target_entity_id>`
- stack_mode: `REPLACE`
- visibility_default: `GODS_ONLY`
- ap_cost: 3
- encounter_cap: 1
- session_cap: 6

### 3) `REVEAL_SECRET`
- deterministic target: `orchestrator.visibility_overlay`
- who_can_propose: `GM`, `AI_GOD`
- who_can_commit: `SYSTEM`
- authority_tier: min 3
- stack_group: `intel_reveal:<target_entity_id>`
- stack_mode: `BLOCK`
- visibility_default: `DM_ONLY`
- ap_cost: 1
- encounter_cap: 1
- session_cap: 4

### 4) `DIVINE_SHIELD`
- deterministic target: `mechanics.apply_condition`
- who_can_propose: `AI_GOD`
- who_can_commit: `SYSTEM`
- authority_tier: min 4
- stack_group: `shield:<target_entity_id>`
- stack_mode: `STACK`
- stack_limit: 2
- visibility_default: `PARTY_ONLY`
- ap_cost: 4
- encounter_cap: 1
- session_cap: 3

## Override resolution
Given interventions in the same `stack_group`:
1. Compare `authority_tier` (higher wins).
2. If tie, compare `occurred_at` (latest wins for `REPLACE`).
3. If still tied, compare lexical `event_id` for deterministic ordering.

## Deterministic mapping table
| action_type | tool target | commit artifact |
|---|---|---|
| BLESS_ATTACK | mechanics.apply_modifier | STATE_DELTA + INTERVENTION_COMMITTED |
| CURSE_DEFENSE | mechanics.apply_modifier | STATE_DELTA + INTERVENTION_COMMITTED |
| REVEAL_SECRET | orchestrator.visibility_overlay | REDACTION_OVERLAY + INTERVENTION_COMMITTED |
| DIVINE_SHIELD | mechanics.apply_condition | STATE_DELTA + INTERVENTION_COMMITTED |

## Rejection requirements
When a proposal violates any registry rule, orchestrator must emit `SYSTEM_WARNING` with:
- `reason_code`
- `failed_stage` (`SCHEMA`, `AUTH`, `AP_CAP`, `AUTHORITY`, `STACK_CONFLICT`)
- original `idempotency_key`

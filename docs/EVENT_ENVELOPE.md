# EVENT_ENVELOPE
Status: Phase 3.0 canonical event envelope specification.

## Canonical JSON Envelope (v1)
Every event produced by any service must conform to this envelope. No alternate wire formats are allowed.

```json
{
  "event_id": "uuid",
  "event_version": 1,
  "contract_version": 1,
  "idempotency_key": "string",
  "type": "INTENT_SUBMITTED",
  "occurred_at": "2026-01-18T20:14:36.210Z",
  "campaign_id": "uuid",
  "session_id": "uuid",
  "encounter_id": "uuid|null",
  "sender": {
    "principal_id": "uuid",
    "entity_id": "uuid|null",
    "role": "GM|PLAYER|AI_DM|AI_NPC|AI_GOD|SYSTEM"
  },
  "payload": {},
  "visibility": {
    "visible_to": ["uuid"],
    "scope": "DM_ONLY|GODS_ONLY|PARTY_ONLY|TELEPATHY_PAIR|CUSTOM"
  },
  "trace": {
    "parent_event_id": "uuid|null",
    "causation_id": "uuid|null",
    "correlation_id": "uuid|null",
    "domain_tags": ["combat.attack"],
    "schema_uri": "ttdm.event.envelope.v1"
  },
  "integrity": {
    "source_service": "orchestrator",
    "sequence_hint": 182,
    "hash": "sha256:optional"
  }
}
```

## Required fields
- `event_version` is required and must be `>= 1`.
- `contract_version` is required and must map to the intervention contract registry version active at commit time.
- `idempotency_key` is required for proposal/commit/retry-safe events. For generated system fan-out events, deterministic derived keys are required (`<parent_event_id>:<event_type>:<n>`).

## JSON Schema (Draft 2020-12)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "ttdm.event.envelope.v1",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "event_id",
    "event_version",
    "contract_version",
    "idempotency_key",
    "type",
    "occurred_at",
    "campaign_id",
    "session_id",
    "sender",
    "payload",
    "visibility",
    "trace"
  ],
  "properties": {
    "event_id": { "type": "string", "format": "uuid" },
    "event_version": { "type": "integer", "minimum": 1 },
    "contract_version": { "type": "integer", "minimum": 1 },
    "idempotency_key": { "type": "string", "minLength": 8, "maxLength": 256 },
    "type": {
      "type": "string",
      "enum": [
        "CHAT",
        "OOC",
        "INTENT_SUBMITTED",
        "INTENT_REJECTED",
        "REACTION_SUBMITTED",
        "TOOL_CALL",
        "TOOL_RESULT",
        "STATE_DELTA",
        "INTERVENTION_PROPOSED",
        "INTERVENTION_COMMITTED",
        "NARRATION",
        "DIALOGUE",
        "SYSTEM_WARNING",
        "REDACTION_OVERLAY"
      ]
    },
    "occurred_at": { "type": "string", "format": "date-time" },
    "campaign_id": { "type": "string", "format": "uuid" },
    "session_id": { "type": "string", "format": "uuid" },
    "encounter_id": { "type": ["string", "null"], "format": "uuid" },
    "sender": {
      "type": "object",
      "additionalProperties": false,
      "required": ["principal_id", "entity_id", "role"],
      "properties": {
        "principal_id": { "type": "string", "format": "uuid" },
        "entity_id": { "type": ["string", "null"], "format": "uuid" },
        "role": { "type": "string" }
      }
    },
    "payload": { "type": "object" },
    "visibility": {
      "type": "object",
      "additionalProperties": false,
      "required": ["visible_to", "scope"],
      "properties": {
        "visible_to": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "type": "string", "format": "uuid" }
        },
        "scope": { "type": "string" }
      }
    },
    "trace": {
      "type": "object",
      "additionalProperties": false,
      "required": ["parent_event_id", "causation_id", "correlation_id", "domain_tags", "schema_uri"],
      "properties": {
        "parent_event_id": { "type": ["string", "null"], "format": "uuid" },
        "causation_id": { "type": ["string", "null"], "format": "uuid" },
        "correlation_id": { "type": ["string", "null"], "format": "uuid" },
        "domain_tags": { "type": "array", "items": { "type": "string" } },
        "schema_uri": { "type": "string" }
      }
    },
    "integrity": {
      "type": "object",
      "additionalProperties": false,
      "required": ["source_service", "sequence_hint", "hash"],
      "properties": {
        "source_service": { "type": "string" },
        "sequence_hint": { "type": "integer", "minimum": 0 },
        "hash": { "type": "string" }
      }
    }
  }
}
```

## Event type payload contracts (summary)
- `INTENT_SUBMITTED`: strict `intent_type`, actor, target refs, and declared AP budget.
- `TOOL_CALL`: deterministic tool name + exact arguments.
- `TOOL_RESULT`: deterministic outputs only (no prose).
- `STATE_DELTA`: mutation patch list with old/new values.
- `NARRATION`/`DIALOGUE`: presentation text only; no hidden mechanics.
- `SYSTEM_WARNING`: rejection reason, policy code, and failed stage.

## Example: proposal -> tool -> delta chain
1. `INTENT_SUBMITTED` by PlayerA with `idempotency_key=enc-555:playerA:turn1:attack`.
2. `TOOL_CALL` generated by orchestrator with parent = intent event.
3. `TOOL_RESULT` from mechanics engine.
4. `STATE_DELTA` committed and persisted in ledger.

All four events must share a `correlation_id` and monotonic replay order.

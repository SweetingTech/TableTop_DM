# LEDGER_SCHEMA
Status: Phase 2.2 append-only ledger specification (Postgres, `ledger` schema).

## Design constraints
1. Ledger tables are append-only: no UPDATE/DELETE for event rows.
2. All events are immutable envelopes with visibility metadata.
3. Replay is deterministic using event order + contract version.

## session_ledger
Columns:
- `seq_id` bigint generated always as identity PRIMARY KEY (ordering anchor)
- `event_id` UUID NOT NULL UNIQUE
- `event_version` int NOT NULL
- `contract_version` int NOT NULL
- `type` text NOT NULL
- `campaign_id` UUID NOT NULL
- `session_id` UUID NOT NULL
- `encounter_id` UUID NULL
- `sender_principal_id` UUID NOT NULL
- `sender_entity_id` UUID NULL
- `payload` jsonb NOT NULL
- `visible_to` uuid[] NOT NULL
- `parent_event_id` UUID NULL
- `domain_tags` text[] NOT NULL default '{}'
- `idempotency_key` text NULL
- `created_at` timestamptz NOT NULL default now()

Constraints:
- CHECK `cardinality(visible_to) > 0`
- CHECK `event_version >= 1`
- FK `parent_event_id` -> session_ledger(event_id) DEFERRABLE INITIALLY DEFERRED
- UNIQUE `(session_id, sender_principal_id, idempotency_key)` WHERE `idempotency_key IS NOT NULL`

Indexes:
- `(session_id, seq_id)` for replay streaming
- `(campaign_id, created_at)`
- `(encounter_id, seq_id)`
- GIN on `visible_to`
- GIN on `domain_tags`
- `(type, created_at)`

## session_summaries
Columns:
- `id` UUID PRIMARY KEY
- `campaign_id` UUID NOT NULL
- `session_id` UUID NOT NULL
- `summary_scope` text NOT NULL CHECK in ('GLOBAL','PRINCIPAL')
- `principal_id` UUID NULL (required for PRINCIPAL)
- `from_seq_id` bigint NOT NULL
- `to_seq_id` bigint NOT NULL
- `summary_text` text NOT NULL
- `visible_to` uuid[] NOT NULL
- `created_at` timestamptz NOT NULL default now()

Constraints:
- CHECK `to_seq_id >= from_seq_id`
- CHECK `(summary_scope = 'PRINCIPAL' AND principal_id IS NOT NULL) OR (summary_scope = 'GLOBAL' AND principal_id IS NULL)`
Indexes:
- `(session_id, to_seq_id DESC)`
- `(session_id, principal_id, to_seq_id DESC)`
- GIN `(visible_to)`

## Redaction overlay mechanism
Redaction is implemented by appending ledger events of type `REDACTION_OVERLAY`.

Overlay payload contract:
- `target_event_id` UUID
- `redaction_kind` enum ('HIDE_FIELD','MASK_TEXT','SUPERSEDE_EVENT')
- `path` JSON pointer or logical field path
- `reason_code` text
- `replacement` optional typed value

Rules:
1. Original event remains immutable.
2. Consumers apply overlays in `seq_id` order at read time.
3. Overlays include their own `visible_to` scope (often narrower than source event).
4. Replay mode can be run in:
   - `raw`: ignore overlays
   - `effective`: apply overlays for caller visibility

## Replay expectations
A replay engine must:
1. Read by `(session_id, seq_id ASC)`.
2. Filter by caller principal visibility (`visible_to @> ARRAY[principal_id]`).
3. Apply redaction overlays in-order.
4. Validate `event_version` and `contract_version` compatibility.
5. Reconstruct deterministic state by applying STATE_DELTA and tool-result records.

## RLS/filter approach
Preferred approach for v1:
- Enable Postgres RLS on `ledger.session_ledger` and `ledger.session_summaries`.
- Request context sets `SET app.principal_id = '<uuid>'`.
- Policy: `visible_to::text[] @> ARRAY[current_setting('app.principal_id', true)]`.

Fallback for non-RLS environments:
- Mandatory repository-layer filter on all reads using `visible_to @> ARRAY[$principal_id]`.
- CI contract test compares RLS and app-filter result sets for parity.

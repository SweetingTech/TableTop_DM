CREATE SCHEMA IF NOT EXISTS ledger;

CREATE TABLE IF NOT EXISTS ledger.session_ledger (
  seq_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_id uuid NOT NULL UNIQUE,
  event_version int NOT NULL CHECK (event_version >= 1),
  contract_version int NOT NULL,
  type text NOT NULL,
  campaign_id uuid NOT NULL,
  session_id uuid NOT NULL,
  encounter_id uuid,
  sender_principal_id uuid NOT NULL,
  sender_entity_id uuid,
  payload jsonb NOT NULL,
  visible_to uuid[] NOT NULL,
  parent_event_id uuid,
  domain_tags text[] NOT NULL DEFAULT '{}'::text[],
  idempotency_key text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (cardinality(visible_to) > 0),
  UNIQUE (session_id, sender_principal_id, idempotency_key),
  FOREIGN KEY (parent_event_id) REFERENCES ledger.session_ledger(event_id) DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS idx_session_ledger_session_seq ON ledger.session_ledger(session_id, seq_id);
CREATE INDEX IF NOT EXISTS idx_session_ledger_campaign_created ON ledger.session_ledger(campaign_id, created_at);
CREATE INDEX IF NOT EXISTS idx_session_ledger_encounter_seq ON ledger.session_ledger(encounter_id, seq_id);
CREATE INDEX IF NOT EXISTS idx_session_ledger_visible_to ON ledger.session_ledger USING gin(visible_to);
CREATE INDEX IF NOT EXISTS idx_session_ledger_domain_tags ON ledger.session_ledger USING gin(domain_tags);
CREATE INDEX IF NOT EXISTS idx_session_ledger_type_created ON ledger.session_ledger(type, created_at);

CREATE TABLE IF NOT EXISTS ledger.session_summaries (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL,
  session_id uuid NOT NULL,
  summary_scope text NOT NULL CHECK (summary_scope IN ('GLOBAL','PRINCIPAL')),
  principal_id uuid,
  from_seq_id bigint NOT NULL,
  to_seq_id bigint NOT NULL,
  summary_text text NOT NULL,
  visible_to uuid[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (to_seq_id >= from_seq_id),
  CHECK ((summary_scope = 'PRINCIPAL' AND principal_id IS NOT NULL)
      OR (summary_scope = 'GLOBAL' AND principal_id IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_session_summaries_session_to_desc ON ledger.session_summaries(session_id, to_seq_id DESC);
CREATE INDEX IF NOT EXISTS idx_session_summaries_session_principal_to_desc ON ledger.session_summaries(session_id, principal_id, to_seq_id DESC);
CREATE INDEX IF NOT EXISTS idx_session_summaries_visible_to ON ledger.session_summaries USING gin(visible_to);

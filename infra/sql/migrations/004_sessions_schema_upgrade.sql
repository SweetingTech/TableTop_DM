CREATE TABLE IF NOT EXISTS state.sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id),
  status text NOT NULL CHECK (status IN ('ACTIVE','PAUSED','ENDED')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  checkpoint_seq_id bigint NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sessions_campaign_status
  ON state.sessions(campaign_id, status);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'encounters_session_id_fkey'
  ) THEN
    ALTER TABLE state.encounters
      ADD CONSTRAINT encounters_session_id_fkey
      FOREIGN KEY (session_id) REFERENCES state.sessions(id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'intents_session_id_fkey'
  ) THEN
    ALTER TABLE state.intents
      ADD CONSTRAINT intents_session_id_fkey
      FOREIGN KEY (session_id) REFERENCES state.sessions(id);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'interventions_session_id_fkey'
  ) THEN
    ALTER TABLE state.interventions
      ADD CONSTRAINT interventions_session_id_fkey
      FOREIGN KEY (session_id) REFERENCES state.sessions(id);
  END IF;
END $$;

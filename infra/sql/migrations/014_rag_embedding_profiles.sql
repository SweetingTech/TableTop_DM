-- 014_rag_embedding_profiles.sql
-- Phase 39 step 6: solve the embedding-dimension lock.
--
-- Symptom: Qdrant collections are created with the dimension of the FIRST
-- upload's embedding. Switch the campaign's embedding_model later (or the
-- provider entirely — text-embedding-3-small=1536 vs nomic-embed-text=768)
-- and every subsequent upload crashes against the locked collection.
--
-- Fix: each (provider, model) combo gets its own profile row + its own
-- Qdrant collection. Switching models means a new profile, a new
-- collection, and existing documents marked NEEDS_REINDEX rather than
-- being silently broken.

CREATE TABLE IF NOT EXISTS state.rag_embedding_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
  provider text NOT NULL,
  embedding_model text NOT NULL,
  -- vector dimension — set when the first upload to this profile completes.
  -- Lookups before that should treat it as unknown.
  vector_dim int NULL,
  -- 8-char hash derived from (provider|model) so the collection name is
  -- stable and short. Computed by services/rag/embedding_profile.py.
  signature text NOT NULL,
  qdrant_collection text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  retired_at timestamptz NULL,
  UNIQUE (campaign_id, signature)
);

CREATE INDEX IF NOT EXISTS idx_rag_profiles_campaign_active
  ON state.rag_embedding_profiles(campaign_id, active);

-- Existing rag_documents rows predate profiles. Add a nullable FK; NULL
-- means "legacy collection" and the resolver falls back to the old
-- naming scheme (ttdm_<campaign_id>_rag) for those.
ALTER TABLE state.rag_documents
  ADD COLUMN IF NOT EXISTS embedding_profile_id uuid
    REFERENCES state.rag_embedding_profiles(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS needs_reindex boolean NOT NULL DEFAULT false;

-- Allow the new status value alongside the existing four.
ALTER TABLE state.rag_documents DROP CONSTRAINT IF EXISTS rag_documents_status_check;
ALTER TABLE state.rag_documents
  ADD CONSTRAINT rag_documents_status_check
  CHECK (status IN ('QUEUED','PROCESSING','READY','FAILED','NEEDS_REINDEX'));

CREATE INDEX IF NOT EXISTS idx_rag_documents_profile
  ON state.rag_documents(embedding_profile_id);

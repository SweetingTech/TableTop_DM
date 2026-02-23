CREATE TABLE IF NOT EXISTS state.campaign_settings (
  campaign_id uuid PRIMARY KEY REFERENCES state.campaigns(id) ON DELETE CASCADE,
  llm_provider text NOT NULL DEFAULT 'mock' CHECK (llm_provider IN ('openai','ollama','lmstudio','mock')),
  llm_base_url text,
  embedding_base_url text,
  dm_model text NOT NULL DEFAULT 'gpt-4o-mini',
  npc_model text NOT NULL DEFAULT 'gpt-4o-mini',
  embedding_model text NOT NULL DEFAULT 'text-embedding-3-small',
  content_mode text,
  settings jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS state.rag_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
  filename text NOT NULL,
  storage_path text NOT NULL,
  status text NOT NULL CHECK (status IN ('QUEUED','PROCESSING','READY','FAILED')),
  enabled boolean NOT NULL DEFAULT true,
  error_text text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rag_documents_campaign_status
  ON state.rag_documents(campaign_id, status);

CREATE TABLE IF NOT EXISTS state.rag_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id uuid NOT NULL REFERENCES state.rag_documents(id) ON DELETE CASCADE,
  campaign_id uuid NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
  chunk_id text NOT NULL,
  page int,
  text text NOT NULL,
  qdrant_point_id text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (doc_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_doc_id ON state.rag_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_campaign_id ON state.rag_chunks(campaign_id);

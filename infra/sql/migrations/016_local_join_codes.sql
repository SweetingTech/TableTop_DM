CREATE TABLE IF NOT EXISTS state.local_join_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES state.campaigns(id) ON DELETE CASCADE,
    session_id UUID REFERENCES state.sessions(id) ON DELETE CASCADE,
    principal_id UUID NOT NULL REFERENCES state.principals(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    label TEXT,
    created_by UUID REFERENCES state.principals(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    UNIQUE (campaign_id, token_hash)
);

CREATE INDEX IF NOT EXISTS idx_local_join_codes_campaign
    ON state.local_join_codes (campaign_id, revoked_at, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_local_join_codes_principal
    ON state.local_join_codes (principal_id, revoked_at);

INSERT INTO infra_meta.schema_migrations(version, checksum)
VALUES ('016_local_join_codes', 'manual')
ON CONFLICT (version) DO NOTHING;

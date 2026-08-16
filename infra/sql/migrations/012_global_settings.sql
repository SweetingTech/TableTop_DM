-- 012_global_settings.sql
-- Installation-wide configuration: API keys, default image-gen settings,
-- anything else that should live per-installation rather than per-campaign.
--
-- Modeled as a key-value store so adding new global settings later doesn't
-- require schema changes. The only currently-defined keys are:
--   'api_keys'      -> jsonb dict { openrouter: "...", openai: "...", ... }
--   'image_gen'     -> jsonb { provider, model, host_model }
--   'last_modified' -> jsonb timestamp string
--
-- This sits *next to* state.campaign_settings, which keeps per-campaign
-- overrides. Image-gen and LLM adapters consult campaign settings first,
-- fall back to global_settings if not configured.

CREATE TABLE IF NOT EXISTS state.global_settings (
  key text PRIMARY KEY,
  value jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_global_settings_updated ON state.global_settings(updated_at);

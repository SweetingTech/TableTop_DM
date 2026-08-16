# Gemini Review Closure Architecture Notes

This note records the cleanup work done after `gemini_code_review.md`.

## API Shape

The Flask app now registers the existing public route surface through an API
blueprint and keeps shared route helpers in `services/api/`. Public URLs remain
stable; auth guards, JSON error responses, serialization, and story-state
redaction live outside the route file.

## State Delta Dispatch

`services/orchestrator/delta_dispatcher.py` owns state-delta application. The
orchestrator no longer hardcodes table/operation branches; it delegates to a
registry with explicit handlers for:

- `state.entities` `UPDATE`
- `state.conditions` `INSERT`
- `state.conditions` `DELETE`

Unknown table/operation pairs raise `UnsupportedStateDeltaError`.

## Campaign Deletion

Campaign purge and game-save import replacement share
`services/campaigns/lifecycle.py`. The service explicitly deletes ledger rows
because the ledger has no campaign foreign key, then deletes the campaign root
row and relies on database cascades for state tables. Migration
`015_campaign_cascade_cleanup.sql` updates the relevant foreign keys.

## Local Providers And RAG

Embedding defaults are provider-aware. OpenAI keeps
`text-embedding-3-small`; Ollama defaults to `nomic-embed-text`; LM Studio
selects an embedding-looking local model when one is discoverable, otherwise
RAG reports a setup error instead of silently attempting OpenAI embeddings.

## Session Intel Robustness

The Session Intel extractor schema now includes explicit enums. If a local
model emits invalid structured output, the extractor retries once with the
validation errors and a constrained event-type list. A small alias map handles
known safe local-model variants such as `npc_relationship_changed`.

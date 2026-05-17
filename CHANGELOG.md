# Changelog

All notable changes to TableTop DM, ordered newest first. Phases reference rows in the README's Implementation Status table.

The project tags features in **Phases** rather than semver — there's no public versioned release surface yet, and date-grouped phases match how the work has actually shipped. Each section links to the commits that delivered it.

---

## Planned — next sprint

Items I'm planning to take on next, in priority order. These are the natural extensions of the design doc's roadmap; happy to reorder if priorities shift.

### Phase 40 — RAG-aware Session Intel
**The loop**: when the extractor sees players mention "the bell" (and the campaign has Saint Orun lore loaded), the extractor should propose a `dm_only unresolved_thread` with the RAG chunk attached as evidence — not just rely on the LLM's training knowledge.

- Thread `retrieve_campaign_context(purpose="session_intel")` through `services/session_intel/extractor.py`.
- `ExtractedStoryEvent.evidence[]` gains a `source_kind="rag_chunk"` variant so DM can audit the lore citation.
- New rule: **RAG-supported inferences always set `requires_dm_review=True`** even at high confidence — observed play can auto-propose, but inferences pulled from lore require human sign-off.

### Phase 41 — Source citations in DM Packet + recaps
The retriever already emits citations. Surface them.

- `POST /api/sessions/<id>/dm_packet` payload gains a `citations: [{filename, page, chunk_id}]` array referenced by patches.
- DM recap mode embeds inline citation markers (e.g. `…the Pale Saint [1]…`) when a recap line was lore-grounded.
- Party recap omits citation markers entirely (they leak source filenames otherwise).

### Phase 42 — Per-principal WebSocket broadcaster
Make the decoherence engine actually filter in real time. Right now `audience_for_event()` computes who *should* see an event, but `socketio.emit(..., room=str(campaign_id))` still yells to the whole room.

- Refactor `broadcast_game_event(event)` helper:
  - Compute audience via `audience_for_event(campaign_id, map_id, x, y)`.
  - Emit to per-principal Socket.IO rooms (`principal:<id>`), not the campaign room.
  - DM principal always gets everything.
  - Public/campaign-wide events still allowed to broadcast to `campaign:<id>`.
- Client-side: each tab joins its own `principal:<id>` room on connect.

### Phase 43 — Per-chunk visibility UI override
Right now chunk visibility is inferred from filename substrings (`dm-only`, `secret`, `party`). That's a stopgap.

- Knowledge Base tab gains a per-chunk visibility editor (party / dm_only / principal_scoped).
- `tags[]` and `entity_ids[]` editable from the same panel — feeds the NPC `known_lore_tags` matching layer.
- On save, the chunk's Qdrant payload is updated in place (no re-embedding required).

### Phase 44 — Reranker (cheap deterministic, then optional LLM)
The doc's caveat is right: cosine top-k retrieves "shopping list, bell peppers, cult classic movies" eventually. Add a deterministic re-rank stage before any LLM polish.

```text
vector_score * 0.70 +
entity_match_score * 0.15 +
location_match_score * 0.10 +
recency_score * 0.05
```

Cross-encoder rerank as an optional second pass once the deterministic version proves out.

### Phase 45+ — further out

- **Audio / transcript ingestion** — `services/transcript/` package mirroring `services/session_intel/`'s shape. Audio → diarized chunks → `ExtractedStoryEvent` proposals → DM review. Schema already supports `source_kind='transcript'`.
- **Continuity timelines per NPC / location** — extension of `npc_memory(...)` that renders a timeline view.
- **Map editor** — DM places POIs / decorations / walls manually in the Three.js renderer. Right now everything is procedural or API-driven.

---

## 2026-05-17 — Phase 39: RAG-grounded DM/NPC cognition

The Knowledge Base was a searchable attic; now it's a brain. Uploaded lore feeds the DMNarrationAgent and NPCDialogueAgent at generation time, filtered for visibility so `dm_only` secrets never leak into party recaps or NPC dialogue regardless of how relevant cosine similarity thinks they are.

- **Added** `services/rag/` package — centralizes retrieval behind a service boundary instead of leaving Qdrant logic smeared through `app.py`.
  - `retriever.py` — `retrieve_campaign_context(campaign_id, query, *, purpose, session_id, entity_ids, top_k, principal_id, npc_known_tags)`. Embeds the query, searches the active embedding-profile collection (legacy collection fallback), applies server-side Qdrant payload filter, runs a client-side visibility re-check, returns a `RagContext` with chunks + prompt-ready `context_block` + citations.
  - `context_builder.py` — `build_dm_narration_context()` / `build_npc_dialogue_context()` compose retrieved chunks + `state.story_state` snapshot into the prompt prefix the agents prepend.
  - `filters.py` — visibility access matrix + `filter_chunk_visibility()` + `build_qdrant_filter()`. The leak boundary lives here.
  - `embedding_profile.py` — solves the embedding-dimension lock. Each `(provider, model)` combo gets a dedicated profile + collection. Switching models retires the prior profile and flips its docs to `NEEDS_REINDEX`.
- **Added** migration `014_rag_embedding_profiles.sql` — `state.rag_embedding_profiles` table + `embedding_profile_id` / `needs_reindex` columns on `state.rag_documents`. Status enum gains `NEEDS_REINDEX`.
- **Changed** `DMNarrationAgent.narrate_event()` — accepts `session_id`, prepends `CAMPAIGN LORE CONTEXT` + `CURRENT STORY STATE`. SYSTEM_PROMPT updated with "do not invent beyond these facts" constraint. Fails open: RAG errors never block narration. Optional `return_citations=True` for dev surfaces.
- **Changed** `NPCDialogueAgent.generate_dialogue()` — accepts `session_id` and `npc_entity_id`. Reads NPC's `public_sheet.known_lore_tags` and tightens retrieval to `public + party` chunks that overlap those tags. SYSTEM_PROMPT explicitly forbids reveals beyond context.
- **Changed** `_process_rag_document()` — now resolves the active embedding profile from current `campaign_settings`, creates the matching Qdrant collection at the correct dimension on first use, writes `visibility` + `tags` into every chunk's payload. Filename-substring hints (`dm-only`, `secret`, `party`) wire visibility end-to-end.
- **Changed** `POST /api/campaigns/<id>/rag/query` — routes through the new retriever instead of talking to Qdrant directly. Accepts optional `purpose=` so callers can match their access context.
- **Tests** — 23 new (`test_rag_filters.py`, `test_rag_embedding_profile.py`, `test_rag_north_star.py`). The north-star tests lock the Black-Bell-of-Saint-Orun acceptance scenario from the design doc: dm_only chapel lore is visible to dm_narration + recap_dm; filtered out of npc_dialogue (even with matching tags) + recap_party + recap_public.
- **87/87 tests passing** (was 64).

Commits: `58f5fa3`

---

## 2026-05-16 — Phases 33–38: Session Intelligence (narrative state compiler)

The original architecture's critique: "you built the engine; you didn't build the sensory cortex." This sprint adds the observer-extractor-reviewer-recap loop that watches chat + ledger, proposes structured narrative deltas with evidence, queues them for DM approval, applies on approval, and surfaces continuity over time. Same prime directive as `/api/propose` — extractor produces schema-validated proposals; deterministic backend commits.

- **Added** migration `013_proposed_story_patches.sql` — `state.proposed_story_patches` review queue with workflow `PENDING → APPROVED|REJECTED|EDITED → APPLIED|SUPERSEDED`.
- **Added** `shared/schemas/session_intel.py` — Pydantic contracts (`Evidence`, `ExtractedStoryEvent`, `ExtractionRequest`, `ExtractionResult`, `DMReviewPacket`), `StoryEventType` enum with 16 kinds.
- **Added** `services/session_intel/` package:
  - `extractor.py` — two paths: **Deterministic** (scans ledger STATE_DELTA / TOOL_CALL rows, confidence 1.0) and **LLM-driven** (DIALOGUE rows + DM notes via `LLMAdapter.generate_structured()` with a strict schema; events without verbatim quote evidence are dropped).
  - `patcher.py` — per-event-type dispatch into `state.story_state` fields. `retcon_or_contradiction` is never auto-applied — flagged in `dm_notes` for DM resolution.
  - `recap.py` — visibility-scoped recaps (`dm` / `party` / `principal` / `public`). Falls back to deterministic bullets if no LLM is configured.
  - `continuity.py` — `open_threads`, `unresolved_promises`, `npc_memory`, `contradictions`.
- **Added** 11 new API endpoints — `/intel/extract`, `/dm_packet`, `/patches` browse + approve/reject/edit, `/recap`, `/open_threads`, `/unresolved_promises`, `/npc_memory/<id>`.
- **Added** Control Plane **Session Intel** tab — patch cards (color-coded by event-group), inline approve/reject/edit actions, visibility-scoped recap viewer, continuity panel with Open Threads / Unresolved Promises / Contradictions side-by-side.
- **Tests** — 5 new (`test_session_intel_patcher.py`) cover the dispatch table.

Commits: `d0046b4`, `9ab6db1`, `d53789f`

---

## 2026-05-16 — Desktop launcher + game-save fixes

- **Added** `scripts/launch_app.ps1` — boots compose + Flask, polls `/readyz`, opens the dashboard.
- **Added** `scripts/install_shortcut.ps1` — drops `Tabletop DM.lnk` on the user's desktop with the `imageres.dll,109` game-controller icon. Idempotent.
- **Fixed** game-save import on campaigns with populated ledger events:
  - `ledger.session_ledger.visible_to` is `uuid[]` and `domain_tags` is `text[]`, not jsonb. The importer was casting both as `::jsonb` and rejecting the Postgres array literal. Now uses native psycopg2 list adapters.
  - `seq_id` is `GENERATED ALWAYS AS IDENTITY`. The importer was including it in INSERTs and failing with "cannot insert a non-DEFAULT value." Now drops `seq_id` and lets Postgres reassign — ordering preserved via insertion order; `parent_event_id` references `event_id` (UUID) not `seq_id` so the parent chain survives.

Commits: `55cef16`, `5044f9a`

---

## 2026-05-11 — API key vault + dedicated API Keys panel

- **Added** `services/saves/vault.py` — installation-local Fernet key at `.local-run/vault.key` (gitignored, mode 0600, outside Docker). API keys are encrypted at rest using this; decrypt happens only at HTTP call sites.
- **Changed** `/api/global_settings/api_keys` PUT — encrypts each value before storing. Empty string deletes a provider's key.
- **Changed** `/api/global_settings` GET — returns `"********"` for every encrypted value. Cleartext never leaves the server after save.
- **Changed** `/api/campaigns/<id>/ai_config` PUT/GET — same encryption pattern for per-campaign API keys.
- **Changed** image-gen + LLM adapter — `_resolve_api_key()` falls back through campaign → global → env, decrypting whichever path hits first.
- **Added** Control Plane **API Keys** tab — one password field per provider (OpenRouter / OpenAI / Anthropic / DeepSeek), status indicators, deep links to each provider's keys page.
- **Changed** `program save` export/import — exports decrypt first (each install has its own vault key), imports re-encrypt with the destination machine's vault. Cleartext only exists inside the passphrase-protected `.ttdm` file.

Commits: `74f81b3`

---

## 2026-05-10 — External encrypted save files + OpenRouter image-gen + visual polish

### External save files (Phases ~32)

Two passphrase-encrypted file kinds stored entirely on the user's local filesystem.

- **Added** `services/saves/`:
  - `crypto.py` — `ttdm-save:v1` file format: JSON header + Fernet token, keyed by PBKDF2-HMAC-SHA256 (600k iterations, 16-byte salt).
  - `game_save.py` — per-campaign export/import. Principal references migrate by `auth_subject`, not UUID.
  - `program_save.py` — installation-wide export/import (global_settings + HUMAN principals).
- **Added** four endpoints: `/api/saves/game/export`, `/api/saves/game/import`, `/api/saves/program/export`, `/api/saves/program/import`.
- **Added** migration `012_global_settings.sql` — installation-wide K/V (API keys + image gen defaults).
- **Added** Control Plane **Save / Load** tab — buttons trigger blob downloads via `URL.createObjectURL`; imports use multipart upload with passphrase prompt.

### OpenRouter image-gen rewrite

- **Changed** `services/domain/maps/image_gen.py` — switched from chat-completions-with-modalities to OpenRouter's documented `openrouter:image_generation` server tool. Two-step: a cheap **host chat model** drives the tool, which invokes the **image model**.
- **Added** dropdown / autocomplete for the 8 known image models (gemini-2.5-flash-image, gemini-3.1-flash-image-preview, gemini-3-pro-image-preview, seedream-4.5, gpt-5.4-image-2, gpt-5-image-mini, flux.2-pro, riverflow-v2-fast).
- **Added** robust response parsing — Gemini-style `images[]`, content-array `image_url`, tool-call result JSON, markdown image syntax.

### Visual polish — Phases 7+8

- **Changed** procedural map generator — now composes coherent scenes per tier instead of rolling each tile independently:
  - **ROOM** — walled enclosure with 1–2 doorway gaps, mostly stone floor, optional wood-plank platform, rubble cluster, basin.
  - **AREA** — biome-dominant (forest / plains / desert / coastal / tundra / town) with a meandering random-walk path of secondary terrain and a feature cluster.
  - **WORLD** — Voronoi-style biome regions from 5–7 seeds + mountain ridge.
- **Added** migration `011_map_decorations.sql` — `state.map_decorations` table for flavor sprites (trees, barrels, chests, torches, etc.). Generator places biome-appropriate decorations during composition.
- **Added** decoration rendering in the Three.js viewer with `DECO_GLYPHS` table covering 19 kinds. `depthTest:true` and lower hover height so they sit *on* the tile.
- **Fixed** movement bug — `controller_principal_id` UUIDs weren't being coerced consistently from the DB; tile-snapped movement wasn't always firing. Resolved in `app.py` and `app.js`.
- **Added** **OpenRouter Test Image Gen** button on the AI Settings panel.

### Three.js map renderer foundation — Phases 0–6f

The first big lift of the sprint replaced the Canvas2D map view with a Three.js scene.

- **Added** `static/js/map_renderer.js` — orthographic camera (FF Tactics tilt), `NearestFilter` baked tile textures, no antialiasing, render-on-demand via `OrbitControls.change`, raycaster click-to-move, WASD/arrow tile-step with map-tab visibility check, OrbitControls right-drag pan + wheel zoom.
- **Added** migrations:
  - `008_map_hierarchy.sql` — `kind` (`WORLD|AREA|ROOM`) + `parent_map_id` on `state.maps`.
  - `009_map_pois.sql` — `state.map_pois` (kind enum, position, image_url, target_map_id, is_hidden, metadata).
  - `010_entity_current_map.sql` — `entities.current_map_id` (party decoherence foundation).
- **Added** auto-generation on first session create — World 40×40 + Area 24×24 + Room 20×20. Deterministic seed from `sha1(campaign_id)`. Idempotent.
- **Added** `services/domain/maps/{perception, decoherence, image_gen}.py`:
  - `perception.py` — class-modulated POI discovery radius (ranger 5, fighter 2, default 3).
  - `decoherence.py` — `audience_for_event(campaign_id, map_id, x, y)` + `transition_entity_map()`.
- **Added** POI proximity reveal on ROOM tier; full clickable labels on WORLD/AREA tiers.
- **Added** Combat HUD — JRPG-style Fight / Item / Spell / Move / End Turn / Flee menu, only shown when the active slot is a PC the player controls. AI-DM uses the same `/api/propose` endpoints without the HUD.
- **Added** Multi-provider scaffolding — OpenRouter / DeepSeek / Anthropic registered alongside OpenAI / Ollama / LM Studio / Mock.

Commits: `c0a461e`, `d5d1bf7`, `d8efe8a`, `6e313a9`, `c9117f2`

---

## Pre-2026-05-10 — Foundation (Phases 0–20)

The deterministic VTT engine that everything else is built on. State authority, append-only ledger, schema-validated proposals, visibility filtering, mechanics/spatial engines, NPC autonomy, factions/economy/divine systems, RAG ingestion (storage layer), maps (upload + procedural), frontend MVP, export/replay, CI/test gates.

See README's [Implementation Status](README.md#implementation-status) table for the full breakdown of Phases 0–20.

Commits on `main` predating this session — `7c7d287` and earlier.

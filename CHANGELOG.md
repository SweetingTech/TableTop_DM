# Changelog

All notable changes to TableTop DM, ordered newest first. Phases reference rows in the README's Implementation Status table.

The project tags features in **Phases** rather than semver — there's no public versioned release surface yet, and date-grouped phases match how the work has actually shipped. Each section links to the commits that delivered it.

---

## 2026-05-17 - Phase 42.9: 1.0 Release Gate and Scope Freeze

The core feature set is now frozen behind a release-candidate gate. The next work is 1.0 hardening: identity, reconnect consistency, golden-path playthrough, route/auth audit, save/load torture, docs, perf, and packaging.

- **Added** `docs/release/1.0-scope.md` - defines the 1.0 contract, in-scope surfaces, post-1.0 cutline, phase reordering, and known release risks.
- **Added** `docs/release/1.0-test-matrix.md` - maps the release gate across boot, lifecycle, identity, player state, ledger, realtime, maps, combat, chat, RAG, Session Intel, save/load, docs, and perf.
- **Added** `docs/release/1.0-security-matrix.md` - documents principal classes, route policy expectations, visibility surfaces, and blocker conditions for auth/visibility leaks.
- **Added** `docs/release/1.0-rc-checklist.md` - captures severity rules, automated gate commands, manual acceptance, packaging requirements, performance smoke budgets, and RC exit criteria.
- **Changed** `README.md` - records Phase 42.9 in the implementation table, points Phase 43+ at the 1.0 RC track, and updates stale party-decoherence wording now that Phase 41 scoped realtime delivery is in place.

---

## 2026-05-17 - Phase 42.8: Full Player State Snapshot

The game client now has a canonical per-principal read model for boot/reload: one snapshot answers who the principal is, what they control, what they can see, what they know, what they can do, and where their visible event stream resumes.

- **Added** `shared/schemas/player_state.py` - Pydantic contracts for the snapshot envelope, controlled entities, visible world, turn state, legal actions, narrative projection, and UI state.
- **Added** `services/player_state/` - read-only snapshot assembly, spatial visibility helpers, serializers, and conservative legal-action calculation.
- **Added** `GET /api/sessions/<session_id>/player_state` - rejects anonymous/non-member access, blocks player `as_principal_id` widening, and allows GM inspection of a simulated player view.
- **Changed** `/game` boot - after campaign/session/principal resolution, the client loads `player_state` first and renders controlled entities, visible entities, visible recent events, story indicators, and socket join context from that snapshot.
- **Tests** - added service, contract, integration, and E2E coverage for auth, controlled-entity scope, DM-only continuity exclusion, principal-scoped event cursors, spatial entity/POI visibility, death state, legal actions, and reload stability.

---

## 2026-05-17 - Phase 42.7: Continuity API visibility hardening

Continuity memory endpoints now require campaign principal context and apply the same visibility rules to NPC memory and promises that already protect recaps and open threads.

- **Changed** `services/session_intel/continuity.py` - `npc_memory`, `open_threads`, and `unresolved_promises` accept visibility scope plus principal id, and principal-scoped rows require `patch.visible_to` to include the requesting principal.
- **Changed** continuity API routes - `/api/campaigns/<id>/npc_memory/<npc_id>`, `/open_threads`, and `/unresolved_promises` reject anonymous callers, reject non-members, and prevent non-DM principals from widening requests to `visibility=dm`.
- **Added** `tests/integration/test_continuity_npc_memory_visibility.py` - covers DM access, player denial of dm-only memory, principal-scoped matching, non-member/anonymous rejection, unresolved-promises auth, and open-thread parity.
- **Changed** realtime broadcaster payload construction - envelope visibility remains canonical when a payload carries a conflicting `visibility`, with a warning so future changes do not silently invert the leak-prevention rule.
- **Tests** - added broadcaster contract coverage for canonical visibility overwrite and warning behavior.

---

## 2026-05-17 - Phase 42.6: App readiness triage

The app now explains readiness failures directly and the E2E suite can run real browser assertions against a cleanly booted stack instead of silently passing over a dead dashboard.

- **Changed** `GET /readyz` - returns structured `ready`, `status`, and per-check `postgres`, `migrations`, `redis`, and `qdrant` objects with `ok`, `latency_ms`, and error details when a dependency fails.
- **Changed** database connections - app DB connections use a bounded `connect_timeout` so readiness and dashboard requests fail diagnostically instead of hanging on an unreachable database.
- **Changed** E2E preflight - probes `/readyz?verbose=1`, writes `test-results-e2e/e2e-readyz.json` and `e2e-root-response.html`, and fails in CI unless `TTDM_E2E_ALLOW_SKIP=1` is set.
- **Added** `tests/integration/test_readiness.py` - covers verbose readiness success, failed dependency identification, and the dashboard route returning 200.
- **Tests** - Playwright E2E now executes the landing-tour and route assertions against a healthy live app instead of skipping.

---

## 2026-05-17 - Phase 42.5: E2E landing tour contract repair

The dashboard guided tour remains a product contract, and the E2E suite now triggers it deterministically instead of depending on first-run localStorage timing.

- **Changed** dashboard tour boot - `/?tour=1` clears the completed flag and starts the tour after DOM setup while preserving normal first-run behavior without the query parameter.
- **Changed** dashboard navigation - exposes the Help route alongside Control Plane and Game Console.
- **Changed** `tests/e2e/test_landing_tour.py` - starts each tour test at `/?tour=1` and keeps coverage for overlay, tooltip, wizard advancement, skip/restart, and the Local AI step.
- **Changed** `tests/e2e/conftest.py` - preflights `/health`, `/readyz`, and `/`, skips cleanly when the app is not ready, and fails tests only on app-owned fatal browser console errors.
- **Added** `tests/e2e/test_routes_smoke.py` - verifies `/`, `/game`, `/control`, and `/help` load with stable titles and navigation markers.

---

## 2026-05-17 - Phase 42: Verification harness + integration repair

The integration suite now boots cross-platform through Python instead of bash path calls, and the realtime visibility layer has end-to-end Socket.IO coverage plus a RAG/Session-Intel/recap continuity matrix.

- **Added** Python integration harness scripts - `scripts/db_reset.py`, `scripts/wait_ready.py`, `scripts/integration_boot.py`, and shared Docker/psql helpers.
- **Changed** `tests/conftest.py` - loads `.env`, uses the Python boot harness, and gives direct RLS tests a non-owner `tabletop` database role.
- **Added** `tests/integration/test_socket_visibility.py` - verifies DM-only, public, principal-scoped, spatial, explicit `visible_to`, and rejected join behavior through actual Socket.IO test clients.
- **Added** `tests/integration/test_visibility_matrix.py` - proves a dm-only RAG-backed patch appears in DM recap/continuity with sources and stays out of party/public recaps and party continuity.
- **Fixed** RLS empty-principal handling - policies now use `NULLIF(current_setting(...), '')::uuid` so `RESET app.principal_id` denies cleanly instead of throwing a UUID cast error.
- **Changed** continuity open-thread queries - support visibility-scoped reads so party-facing continuity cannot see `dm_only` threads.
- **Tests** - full `tests/integration` now passes on Windows through the Python harness.

---

## 2026-05-17 - Phase 41: Per-principal realtime broadcaster

Realtime socket delivery now routes through a single broadcaster instead of raw campaign-room emits. Scoped events deliver by principal, DM-only events deliver only through the DM room, public events use the public campaign room, and spatial events reuse the party decoherence audience resolver.

- **Added** `services/realtime/` - room naming, join validation, audience resolution, normalized `BroadcastEnvelope`, and `broadcast_game_event()`.
- **Changed** app socket delivery - proposal results, NPC autonomy results, chat ledger events, and turn advancement now route through the broadcaster.
- **Changed** socket join flow - `join_campaign` validates campaign membership and joins `principal:<id>` and `session:<id>`, then joins GM/system principals to `dm:<campaign_id>` and non-DM principals to `campaign:<campaign_id>:public`.
- **Changed** frontend socket setup - the browser joins realtime rooms only after campaign, session, and principal context are known.
- **Changed** orchestrator result payloads - committed proposal results now carry `campaign_id`, `session_id`, and `visible_to` so realtime delivery can honor ledger visibility.
- **Tests** - added broadcaster coverage for DM-only, public, principal-scoped, explicit visible_to precedence, spatial routing, DM filtering, join rejection, and legacy campaign-room avoidance.

---

## 2026-05-17 - Phase 40: RAG-aware Session Intel + packet citations

Session Intel now retrieves campaign lore with `retrieve_campaign_context(purpose="session_intel")` before the LLM extraction pass. RAG context is prompt-only: it can support a proposed story patch, but it cannot mutate `state.story_state` or bypass DM review.

- **Added** `services/session_intel/rag_context.py` - builds extraction queries from ledger windows, retrieves RAG context, hydrates `rag_chunk` evidence with doc/chunk/filename/visibility/excerpt metadata, and converts evidence into API-facing `sources`.
- **Changed** `shared.schemas.session_intel.Evidence` - adds `source_kind="rag_chunk"` plus doc/chunk/filename/page/visibility/excerpt/score fields.
- **Changed** `services/session_intel/extractor.py` - LLM extraction receives lore context when available; RAG-backed events are forced to `requires_dm_review=True`; any event resting on `dm_only` lore is forced to `visibility="dm_only"`. RAG failures fail open and do not block normal extraction.
- **Changed** recap and continuity surfaces - recap responses now include `sources`; continuity rows attach source metadata derived from patch evidence.
- **Changed** `POST /api/sessions/<id>/dm_packet` - pending patches include `sources`, recaps include `party_recap_sources` / `dm_recap_sources`, and `citations` aliases DM-visible sources for packet consumers.
- **Changed** Control Plane Session Intel cards - RAG evidence now renders with source filename, visibility, and excerpt alongside ledger quotes.
- **Tests** - added focused coverage for RAG-backed extraction review rules, fail-open behavior, row source-kind compatibility, and recap source visibility filtering.

---

## Planned - 1.0 release-candidate track

The immediate track is release hardening, not new feature expansion. The full gate lives under `docs/release/`.

### Phase 43 - Local identity and join-flow hardening

- Local principal selection/login screen.
- DM principal protected by setup passphrase or local admin mode.
- Player join codes or invite tokens.
- Campaign and session membership enforced on every API and WebSocket path.
- Players cannot pass another `principal_id` or widen visibility by query param.

### Phase 44 - Snapshot/delta/reconnect consistency

- `player_state` event cursor reconciles with WebSocket ledger ids/sequences.
- Client detects cursor gaps and refetches the snapshot.
- Reload/reconnect does not duplicate events or widen state.
- Control handoff updates player state and socket context.

### Phase 45 - V1 golden-path E2E playthrough

- Clean stack boot.
- Campaign/session/player setup.
- Player joins `/game`, moves, discovers POI, chats, fights, saves, restarts, and resumes.
- No DM-only leakage across reload or reconnect.

### Phase 46+ - release gate closure

- Route/auth/visibility matrix audit.
- Save/load torture suite.
- DM packet review UX hardening.
- Docs reality pass.
- Performance smoke and release packaging.

### Post-1.0

- RAG reranker.
- Advanced per-chunk visibility UI polish, unless a smaller control is required for a 1.0 security gate.
- Transcript/audio ingestion.
- Continuity timelines per NPC/location.
- Map editor and extra map themes.

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

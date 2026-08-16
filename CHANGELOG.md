# Changelog

All notable changes to TableTop DM, ordered newest first. Phases reference rows in the README's Implementation Status table.

The project tags features in **Phases** rather than semver — there's no public versioned release surface yet, and date-grouped phases match how the work has actually shipped. Each section links to the commits that delivered it.

---

## 2026-08-16 - Phase 57: Authorization, Portability, and Runtime Review Closure

A fresh review against current `main` closed authorization, visibility, portable-save, readiness, and browser-runtime defects found in the 1.0 surface.

- **Fixed** route authorization - campaign, session, entity, POI, Story State event, and archive mutations resolve resource ownership and require validated GM identity; archive attribution now comes from that identity rather than request data.
- **Fixed** Story State history visibility - player responses redact private fields inside historical snapshots while GM responses retain the full record.
- **Fixed** cross-machine game saves - exports include every referenced principal, and imports remap members, entity controllers, ledger senders, and `visible_to` audiences by `auth_subject`, rejecting incomplete mappings. Legacy principal existence checks are batched into one UUID-array query.
- **Fixed** startup, readiness, and runtime declarations - PostgreSQL probes target the final TCP listener instead of the temporary initialization socket, the expected migration is derived from the repository migration set, readiness requires an exact version match, and `cryptography` is an explicit application dependency.
- **Fixed** realtime and browser compatibility - Flask-SocketIO uses the Flask 3-compatible session mode, Control Plane mutations reuse persisted real GM tokens with the local-demo smoke-token fallback, and Game Console startup uses the read-only session list.
- **Tests** - expanded route/auth, save/load, readiness, runtime dependency, Control Plane, and golden-path coverage; compile, lint, type, JavaScript syntax, service/contract, integration, live E2E, and in-browser checks pass.

---

## 2026-05-19 - Phase 56: RC Burn-Down and Tag Prep

The 1.0 RC checklist now reflects the implemented release gates and known limitations.

- **Changed** `docs/release/1.0-rc-checklist.md` from generic pending rows to concrete automated/manual status for boot, demo mode, DM setup, join flow, player state, movement, combat, visibility, reconnect, save/load, DM packet review, readiness, and docs.
- **Added** `docs/release/1.0-known-limitations.md` documenting local identity scope, deferred route/frontend physical decomposition, local-provider embedding requirements, small-model Session Intel reliability, and final clean-VM packaging verification.
- **Changed** README implementation status to mark Phase 56 as RC burn-down/tag prep complete.

## 2026-05-19 - Phase 55: Packaging Gate

The release artifact path now has a script, first-run instructions, checksums, and an env-template guard.

- **Added** `release/README-FIRST.md` with prerequisites, first-run commands, local LLM notes, troubleshooting, and verification commands.
- **Added** `scripts/package_release.ps1` to produce `release/TableTopDM-v1.0.0.zip` and `release/checksums.txt`.
- **Changed** `.env.example` to include runtime variables used by the app and scripts, including local identity, local provider, readiness, vault, RAG, and debug controls.
- **Added** `tests/contracts/test_env_example.py` so runtime environment variables referenced by Python code cannot drift away from `.env.example`.

## 2026-05-19 - Phase 54: Performance Smoke Baseline

The release budgets now have an automated smoke test and baseline document.

- **Added** `tests/integration/test_v1_perf_smoke.py` covering local `player_state`, WebSocket fanout, RAG query response behavior, and save export budgets.
- **Added** `docs/release/1.0-perf-baseline.md` documenting the budgets, commands, automated coverage, and known local-demo limits.
- **Changed** release test matrix to point at the perf smoke and boot verification gate.

## 2026-05-19 - Phase 53: Docs Reality Pass

The user-facing docs now line up with the current RC surface.

- **Added** `docs/wiki/characters.md` so README/help links to character creation no longer point at a missing page.
- **Changed** README - removed stale `TODO.md` references, documented `gemini_code_review.md` as a historical review-and-closure record, and pointed release truth at README/CHANGELOG/release docs.
- **Changed** old placeholder docs - Phase 0 placeholder language now identifies historical stubs instead of promising future TODO phases.
- **Changed** release docs - docs checklist and test matrix now reflect the completed docs reality pass.

## 2026-05-19 - Phase 52: DM Packet Review UX

The Session Intel review surface now supports release-grade batch review and correction workflows.

- **Added** `/api/patches/batch` for batch approve/apply and batch reject of selected pending patches.
- **Added** `/api/patches/<id>/supersede` so a DM can retire an existing proposal and create a new pending replacement instead of losing provenance.
- **Changed** Control Plane Session Intel - patch cards now have checkboxes, batch approve/reject controls, ledger seq/id evidence labels, and a Supersede action.
- **Changed** recap workflow - batch approval refreshes continuity and the DM recap so edited/applied state is less likely to leave stale review text on screen.
- **Tests** - integration coverage proves batch approval applies state and supersede creates a pending replacement while marking the original `SUPERSEDED`.

## 2026-05-19 - Phase 51: Save/Load Torture Suite

The encrypted `.ttdm` path now has broader failure-mode and RAG metadata coverage.

- **Changed** save decryption - future save schema versions now fail clearly instead of attempting an unsafe import.
- **Changed** game saves - campaign export/import now includes RAG embedding profiles, document records, and chunk metadata so knowledge-base state survives replace restores.
- **Tests** - save/load integration now covers bad magic, corrupt header, truncation, wrong format, unsupported file version, future schema version, wrong save kind, wrong passphrase, replace conflict, replace restore, player state after restore, and RAG metadata/profile roundtrip.
- **Docs** - manual golden-path QA now includes save/load torture checks and cross-install program-save validation.

## 2026-05-19 - Phase 50: Route/Auth/Visibility Matrix Completion

The route/auth matrix now has a generated inventory of every registered Flask route.

- **Changed** `docs/release/1.0-route-auth-matrix.md` - added an explicit route inventory with route path, methods, endpoint name, and policy-family pointer for every non-static Flask route.
- **Added** `tests/contracts/test_route_auth_matrix_inventory.py` - fails if a registered route is absent from the route/auth matrix, preventing future untracked API surface growth.

## 2026-05-19 - Phase 49: V1 Golden-Path E2E Expansion

The golden-path release test now walks a real DM/player flow instead of only probing the seeded demo.

- **Changed** `tests/e2e/test_v1_golden_path.py` - creates a fresh campaign/session/player, generates a join code, creates and seats a PC/NPC, opens `/game` as the player, sends chat, moves, starts combat as DM, exports a save, verifies conflict import behavior, reloads, and checks for DM-only leakage.
- **Added** `docs/release/1.0-golden-path-manual-qa.md` - manual release script matching the automated golden path for fresh checkout or release-artifact validation.

## 2026-05-19 - Phase 48: Snapshot / Delta / Reconnect Edge Cases

The `/game` runtime now treats reconnect and ownership-change events as reasons to refresh the authoritative `player_state` snapshot.

- **Changed** socket reconnect behavior - when the Socket.IO connection reconnects after session/principal context is known, `/game` rejoins scoped rooms and refetches `player_state`.
- **Changed** realtime delta handling - control-handoff shaped events (`entity_control_changed`, `control_version`, or `controller_principal_id`) trigger a snapshot refetch so commandability cannot stay stale.
- **Tests** - E2E now covers reconnect-triggered snapshot refresh, control-handoff refresh, duplicate realtime event suppression, cursor-gap refetch, and two tabs using the same player principal without exposing the identity selector.

## 2026-05-19 - Phase 47: Local Identity and Join UX

The local identity surface now has revocable join-code infrastructure instead of relying only on deterministic smoke tokens.

- **Added** `state.local_join_codes` in migration `016_local_join_codes.sql` for campaign/session-bound local join codes with revoke support.
- **Added** local identity helpers for strict join-token mode, token hashing, smoke-token compatibility, code creation, validation, listing, and revocation.
- **Changed** session principal enforcement - when `TTDM_REQUIRE_JOIN_TOKEN=1`, session-scoped principal guards require a validated join token instead of accepting `principal_id` alone.
- **Changed** `/api/sessions/<id>/join`, `/api/sessions/<id>/player_state`, and Socket.IO `join_campaign` to validate real local join codes in strict mode.
- **Added** Control Plane join-code management - campaign members can get a generated join link and active codes can be revoked.
- **Tests** - route-auth matrix now covers strict-mode join-token rejection, code creation, session join, player-state access, list, revoke, and post-revoke denial.

## 2026-05-19 - Phase 46: Doc Cleanup

The closure-review docs now read consistently before final RC stamping.

- **Docs** - `gemini_code_review.md` now distinguishes the original Gemini CLI review from the Codex closure-pass authorship.
- **Docs** - Section 4.2 clarifies that the route surface is centralized behind a blueprint, while per-domain route-module splitting remains post-1.0 maintainability work.
- **Docs** - README no longer points to deleted `TODO.md`; it points to the release checklist and scope docs.

## 2026-05-19 - Gemini Review Closure

The remaining actionable items from `gemini_code_review.md` have moved from deferred cleanup into implementation work.

- **Docs** - fixed the Gemini review byline so the original review remains attributed to Gemini CLI while the closure pass is clearly authored by Codex.
- **Docs** - clarified that Phase 45 centralized the route surface behind a blueprint and extracted shared helpers, while a per-domain split of `services/api/application.py` is deferred to post-1.0.
- **Docs** - removed the stale README `TODO.md` pointer and replaced it with the release checklist/scope docs.
- **Changed** API structure - public routes now register through a Flask blueprint and shared route helpers moved into `services/api/` for auth, error responses, serialization, and story-state redaction.
- **Changed** app entrypoint - root `app.py` is now a small launcher/composition surface that imports the configured Flask app and Socket.IO instance from `services/api/application.py`, while preserving the public launcher contract.
- **Changed** state mutation - `OrchestratorPipeline` now delegates committed state deltas to `StateDeltaDispatcher` instead of hardcoding table/operation branches inline.
- **Changed** campaign purge/import replacement - purge and save import replacement share a campaign lifecycle service, backed by migration `015_campaign_cascade_cleanup.sql` so database cascades own dependent state cleanup.
- **Fixed** local-provider RAG setup - LM Studio/Ollama no longer silently inherit OpenAI's `text-embedding-3-small`; local providers require or detect local embedding-capable models and fail RAG setup clearly when missing.
- **Fixed** Session Intel local-model resilience - extractor schemas now use explicit enums, safe event aliases are canonicalized, and invalid local-model structured output gets one constrained correction retry.
- **Changed** frontend loading - Game Console and Control Plane now load ES module entrypoints under `static/js/game/` and `static/js/control/`, while compatibility stubs preserve the old asset paths.
- **Added** broad-exception boundary guard - route-layer broad `Exception` catches must be explicitly marked as defensive boundaries, with a contract test preventing silent reintroduction.
- **Docs** - added `docs/architecture/gemini-review-closure.md` to document the new dispatcher, cascade ownership, local embedding behavior, and extractor retry policy.
- **Docs** - README and `gemini_code_review.md` now record the closure status and remaining RC posture.
- **Tests** - added dispatcher, local embedding default, Session Intel retry, route registration, and exception-boundary coverage.
- **Verified** - `python -m compileall -q app.py services shared tests infra`, `ruff check .`, `ruff format --check .`, `mypy .`, Node syntax checks for the game/control module entrypoints, `pytest tests\services tests\contracts tests\integration -q`, `.\scripts\verify_boot.ps1 -Mode docker`, and live E2E browser smoke all pass.

## 2026-05-19 - Phase 44: 1.0 Route Auth, Visibility, and Runtime QA Closure

Runtime QA findings from `gemini_code_review.md` are now treated as 1.0 blockers: route-layer auth and visibility must match the engine's principal-scoped architecture before release.

- **Fixed** session read leaks - chat history, resume data, recaps, and Story State reads now require principal context and use non-widening visibility for players.
- **Fixed** story-state and mode mutation auth - Story State writes and campaign mode changes now require validated local GM/system identity.
- **Fixed** entity mutation auth - entity update, delete, restore, control, and portrait mutation routes now require validated local GM/system identity after resolving the entity's campaign.
- **Fixed** missing NPC dialogue in history - `DIALOGUE` ledger events are included in chat history and resume data once filtered by visibility.
- **Fixed** traceback disclosure - proposal and chat failures return structured errors without Python tracebacks unless `TTDM_DEBUG=1`.
- **Fixed** Windows launcher handling - `scripts/start.ps1` no longer treats normal Docker Compose stderr/progress output as a terminating PowerShell error; it fails on actual nonzero exit codes.
- **Tests** - expanded the route/auth matrix to cover anonymous/non-member rejection, player non-widening reads, GM-authorized mutation, DIALOGUE visibility, traceback suppression, and the updated release matrix rows.

---

## 2026-05-18 - Phase 43.2: Browser QA Auth and Character Generation Fixes

Manual browser QA issues #35, #36, and #37 are closed at the product contract level instead of only hiding symptoms.

- **Fixed** Game Console identity scope - regular player views no longer render a principal selector with DM, God, NPC-agent, or other-player identities; GM views keep an inspection selector.
- **Changed** `/game` principal handling - the authenticated local principal stays distinct from a GM's inspected player view, and player-state calls include the local join-token context.
- **Fixed** DM-only Game Console controls - Start Encounter, Advance Initiative, and AI Narration are hidden for non-GM users and remain visible for GM users.
- **Added** backend enforcement for DM-only controls - encounter creation, initiative advancement, and `/api/narrate` now require a GM/system principal with validated local GM identity, returning 401/403 for missing or player context.
- **Changed** Control Plane AI Generate - the primary button now saves the generated character immediately, reports `Created <name>`, refreshes the character list, and only clears the concept after a successful save.
- **Tests** - added route-auth coverage for DM-only route denials/allowance, persisted AI generation coverage, and E2E assertions for player-vs-GM Game Console controls.

---

## 2026-05-18 - Phase 43.1: Manual QA Defect Repair

The first full manual QA pass found release-blocking gaps in the local LLM path, player identity flow, player-state visibility, combat setup, event-feed readability, AI autonomy, and DM packet recaps. This patch repairs those surfaces and adds regression coverage.

- **Fixed** local LM Studio/Ollama testing - OpenAI-compatible local providers now use a harmless dummy key when no API key is configured, so mock/no-key local play works with LM Studio at `localhost:1234`.
- **Fixed** player-state leakage - player snapshots no longer include controlled-entity `private_sheet`; GM snapshots still retain private sheets for GM-owned inspection.
- **Added** local player creation flow - Control Plane can create campaign player principals, lists player/open links, and `/game` supports explicit `principal_id` selection plus a principal picker.
- **Changed** character ownership controls - character create/edit forms can assign a player controller principal, and AI-controlled entities get a campaign AI controller principal automatically.
- **Added** encounter start flow - `/api/campaigns/<id>/encounters` supports `POST`, and the Game Console exposes a Start Encounter action using session characters/visible entities.
- **Fixed** combat labels - encounter dropdowns and turn advancement fall back to stable encounter/entity labels instead of rendering `undefined`.
- **Fixed** Game Console narration context - `/narrate` and the AI Narration button now include `campaign_id`, `session_id`, and campaign metadata.
- **Changed** event feed rendering - movement/state/tool payloads render concise user-readable summaries instead of raw JSON blobs.
- **Changed** DM recaps - recap text now includes recent visible ledger events as a deterministic fallback when active play happened before Session Intel created patches.
- **Tests** - added local-provider, manual-QA regression, player-state private-sheet, encounter creation, member creation, and ledger-recap fallback coverage; service, contract, integration, compile, JS checks, E2E, and Docker boot smoke pass.

---

## 2026-05-17 - Phase 43: 1.0 Boot, Recovery, and Verification Hardening

The release-candidate track now verifies the local boot path and the highest-risk recovery surfaces instead of relying on architectural intent.

- **Fixed** Docker startup scripts - `migrate.sh`, `seed_demo.sh`, `start.sh`, and `stop.sh` now call Compose with the repo-root `.env` and `infra/docker-compose.yml` explicitly, avoiding Windows/Git-Bash working-directory drift.
- **Changed** app startup - `app.py` now reads `TTDM_DEBUG`; launcher mode defaults to no Flask debug reloader, preventing duplicate port-8000 bind failures on Windows.
- **Added** `scripts/verify_boot.ps1` - stops, starts, probes `/health`, `/readyz?verbose=1`, `/`, `/game`, `/control`, and `/help`, then stops the stack.
- **Added** save/load roundtrip coverage - game export/import checks the `.ttdm` envelope, wrong-passphrase failure, conflict rejection, replace restore, ledger `visible_to`, and `player_state` after import; program save tests API-key portability and re-encryption.
- **Changed** save header schema version - `.ttdm` files now advertise schema version 14 to match the current migration set.
- **Changed** realtime/player-state recovery - committed proposal results now carry `seq_id`; `/game` tracks seen event ids/sequences, ignores duplicate realtime events, and refetches `player_state` on cursor gaps.
- **Added** local join-token guard - `/api/sessions/<id>/join` accepts deterministic local join tokens and enforces them when `TTDM_REQUIRE_JOIN_TOKEN=1`, while preserving current local-demo behavior by default.
- **Added** route/auth release matrix - `docs/release/1.0-route-auth-matrix.md` declares route-family access policy and `tests/integration/test_route_auth_matrix.py` locks the highest-risk principal-scoped denials.
- **Added** V1 golden-path smoke - browser/API E2E covers dashboard -> `/game` player-state boot -> session join -> chat -> save export -> reload without DM-only leakage.

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

### Phase 44 - Fuller local identity and join-flow UI

- Local principal selection/login screen.
- DM principal protected by setup passphrase or local admin mode.
- Player join-code management in the Control Plane.
- Campaign and session membership enforcement expanded across the remaining local-demo routes.

### Phase 45 - Snapshot/delta/reconnect consistency expansion

- `player_state` event cursor reconciles with WebSocket ledger ids/sequences.
- Reconnect after server restart is tested end-to-end.
- Control handoff updates player state and socket context across open tabs.

### Phase 46 - V1 golden-path E2E expansion

- Clean stack boot.
- Campaign/session/player setup.
- Player joins `/game`, moves, discovers POI, chats, fights, imports a save, restarts, and resumes.
- No DM-only leakage across reload or reconnect.

### Phase 47+ - release gate closure

- Route/auth/visibility matrix completion.
- Save/load RAG/import torture expansion.
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

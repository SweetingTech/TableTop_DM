# TODO: Headless Multi-Agent AI VTT Engine (Ship Sequence)
Rule: follow the Mandatory Build Order. No re-architecture. No shortcuts.
Rule: [x] means implemented AND verified by tests or smoke gates. Not “written somewhere”.

---

## Build Order Snapshot (Canonical)
1. Contracts + schemas (`shared/schemas`, `docs/*contract*`).
2. DB migrations and seed (`infra/sql/migrations`, `infra/sql/seed`).
3. Deterministic engines (`services/mechanics`, `services/spatial`).
4. Orchestrator pipeline (`services/orchestrator`).
5. Visibility + ledger enforcement (DB + shared modules; services optional but must be consistent).
6. Session lifecycle + checkpointing + replay gates.
7. Domain systems (social, karma/divine, NPC/maps/content).
8. UI + WebSocket consumption (`templates`, `static` OR `frontend`, pick one and enforce).
9. CI gates (`.github/workflows/ci.yml`, `make ci`) + Playable Smoke Gate.

---

## Reality Gates (NEW, REQUIRED)
### RG0: One-command local boot and shutdown
- [x] `make up` (or `./scripts/start.*`) starts infra + services + UI
- [x] migrations run automatically on start (or `make migrate` is required step)
- [x] seed demo world runs automatically (or `make seed` is required step)
- [x] `make down` (or `./scripts/stop.*`) stops cleanly

Acceptance:
- Fresh clone → run start → open UI → stop → no orphan containers, no stuck ports.

### RG1: Playable Smoke Gate (DM + Player)
- [x] DM can create/load a seeded campaign + session
- [x] Player can join session (principal auth stub ok)
- [x] Load a demo map (2D upload OR seeded procedural)
- [x] Spawn tokens and render them
- [x] Player moves token → server validates → broadcast delta → UI updates
- [x] Player talks to NPC (directed) → NPC responds (only when audible)
- [x] GM switches mode to COMBAT explicitly
- [x] Run 1 full combat round with:
  - [x] intent broadcast
  - [x] pre-registered reaction trigger firing with zero LLM calls
  - [x] deterministic tool calls
  - [x] STATE_DELTA ledger events
- [x] Export session log (visibility filtered) produces Markdown
- [x] Replay from checkpoint reproduces same state (bit-for-bit or loud fail)

Acceptance:
- This is the minimum definition of “play”.

### RG2: CI Green on main
- [x] CI runs with zero secrets (MockLLM in CI)
- [x] CI boots infra, migrates, seeds, runs tests, runs smoke checks
- [x] CI fails if:
  - [x] ledger is mutable
  - [x] visibility filtering bypassed
  - [x] unknown action_type not rejected
  - [x] deterministic engines nondeterministic under seeded RNG tests

Acceptance:
- GitHub Actions shows green on default branch.

---

## Phase 0: Repo + Contracts
### 0.0 Create repo structure
- [x] Create /infra, /services/*, /frontend, /docs
- [x] Add README.md (from this repo)
- [x] Add TODO.md (this file)
- [x] Add /docs placeholders (all present)

NEW REQUIRED FILES:
- [x] Add start/stop scripts:
  - [x] `scripts/start.sh`, `scripts/stop.sh`
  - [x] `scripts/start.ps1`, `scripts/stop.ps1`
- [x] Add `scripts/test.sh` that CI calls
- [x] Add `.env.example` and ensure start scripts copy it if missing

Acceptance:
- Repo boots with canonical scripts and consistent commands.

---

## Phase 1: Infra (Docker)
### 1.0 Docker compose for dependencies
- [x] Postgres (State + Ledger; separate schemas or separate DBs)
- [x] Redis (pubsub + presence + job queues)
- [x] Qdrant (vector DB)
- [x] Add env.example with all required vars

NEW REQUIRED:
- [x] Compose healthcheck gate in scripts/CI (wait until healthy)
- [x] Explicit ports documented in README
- [x] `make up/down/migrate/seed/test/ci` (or equivalent) is canonical and documented

---

## Phase 2: Data Model (Lock semantics before code)
(Claimed done; verify via RG2 + schema tests)
- [x] Object model docs
- [x] State DB schema spec
- [x] Ledger DB schema spec
- [x] Security and visibility spec

NEW REQUIRED:
- [x] Confirm the implementation matches docs (schema drift test in CI)

---

## Phase 3: Event Envelope + Contracts
(Claimed done; verify via contract validation tests)
- [x] Event envelope definition includes event_version/contract_version/idempotency_key
- [x] Intervention registry spec
- [x] Domain tags spec

NEW REQUIRED:
- [x] Contract schema tests in CI:
  - [x] invalid envelope rejected
  - [x] unknown action_type rejected + SYSTEM_WARNING logged

---

## Phase 4: Migrations + Seed Data
### 4.0 Implement migrations
- [x] Create migration toolchain
- [x] Implement State DB schema
- [x] Implement Ledger DB schema
- [x] Add indexes

### 4.1 Seed a demo campaign
- [x] Create sessions table OR equivalent canonical session record (REQUIRED)
- [x] Seed must create:
  - [x] campaign
  - [x] session row
  - [x] principals
  - [x] entities (2 PCs, 1 NPC)
  - [x] one map room
  - [x] encounter template
- [x] Seed prints IDs and writes a “smoke join token” for DM and Player

Acceptance:
- RG1 can be executed from seed output alone.

---

## Phase 5: Deterministic Engines (Mechanics + Spatial)
(Claimed done; must be proven by deterministic tests)
- [x] Mechanics endpoints + tests
- [x] Spatial endpoints + tests

NEW REQUIRED:
- [x] Integration test: Orchestrator calls mechanics + spatial and commits deltas atomically

---

## Phase 6: Orchestrator/Router Core
(Claimed done; must be proven end-to-end)
- [x] REST + WebSocket interfaces
- [x] COMBAT loop
- [x] Validation pipeline
- [x] Concurrency + idempotency

NEW REQUIRED:
- [x] “Unknown action_type” rejection writes SYSTEM_WARNING ledger entry (assert in integration test)
- [x] Encounter/session locks proven by concurrency test

---

## Phase 7: Visibility Enforcement End-to-End
(Claimed done; must be proven with hard tests)
- [x] Ledger writes include visible_to[]
- [x] Context assembly filtering

NEW REQUIRED:
- [x] WebSocket broadcast filtering test (server-side filtering, not client filtering)

---

## Phase 8: LLM Adapter Layer (Text Only)
(Claimed done; add CI-safe mode)
- [x] LLM adapter
- [x] DM agent narration only
- [x] NPC agent directed only

NEW REQUIRED:
- [x] MockLLM adapter mode for CI and local dev:
  - [x] no external inference calls
  - [x] deterministic fixture proposals and dialogue

---

## Phase 9: Schrödinger’s Conversation
(Claimed done; verify token discipline)
- [x] Olympus loop
- [x] On-screen proximity
- [x] Off-screen simulation deltas only

NEW REQUIRED:
- [x] Test: off-screen simulation produces no LLM calls (assert call count = 0)

---

## Phase 10: Karma + Divine Standing
(Claimed done; verify thresholds)
- [x] Tag stamping
- [x] Standing updates
- [x] Threshold wakes

NEW REQUIRED:
- [x] Test: threshold wake triggers only on crossings, not on every tagged event

---

## Phase 11: Divine System
(Claimed done; verify ordering)
- [x] Equal AP + caps
- [x] Authority + override order rules
- [x] Grudges

NEW REQUIRED:
- [x] Integration test: elder-first then minor-second effect sticks until countered (ordering proof)

---

## Phase 12–16: NPC, Social, Guilds, Economy, Content
(Claimed done; verify consequence chains and toggles)
NEW REQUIRED:
- [x] Campaign toggles integration tests (content mode, divine enabled/disabled, etc.)
- [x] Murder-hobo consequence smoke test from RG1 (kill villager → bounty/investigation event)

---

## Phase 17: Maps
(Claimed done; must prove in RG1)
NEW REQUIRED:
- [x] “Map truth” test:
  - [x] collision mask blocks movement server-side
  - [x] UI reflects blocked move as rejection

---

## Phase 18: Frontend MVP
(Claimed done; must prove in RG1)
NEW REQUIRED:
- [x] Two-client test harness (DM + Player) for WS feed differences (visible_to proven)

---

## Phase 19: Export + Replay + Debugging
(Claimed done; must prove state reproduction)
NEW REQUIRED:
- [x] Replay test:
  - [x] checkpoint + ledger replay reproduces state exactly OR fails loud with diff output

---

## Phase 20: Hardening + Ops
(Claimed done; CI proves it)
NEW REQUIRED:
- [x] CI uses canonical scripts (`scripts/test.sh` or `make ci`)
- [x] CI executes RG-lite smoke:
  - [x] /health OK
  - [x] migrations OK
  - [x] seed OK
  - [x] 1 proposal → tool call → delta → ledger append

---

## Burn Bag (Optional but you requested it)
- [x] Create `burn-bag/` for temporary smoke tests only
- [x] Permanent unit/integration tests stay in normal test folders

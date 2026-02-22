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
- [ ] CI runs with zero secrets (MockLLM in CI)
- [ ] CI boots infra, migrates, seeds, runs tests, runs smoke checks
- [ ] CI fails if:
  - ledger is mutable
  - visibility filtering bypassed
  - unknown action_type not rejected
  - deterministic engines nondeterministic under seeded RNG tests

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
- [ ] Add start/stop scripts:
  - [ ] `scripts/start.sh`, `scripts/stop.sh`
  - [ ] `scripts/start.ps1`, `scripts/stop.ps1`
- [ ] Add `scripts/test.sh` that CI calls
- [ ] Add `.env.example` and ensure start scripts copy it if missing

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
- [ ] Compose healthcheck gate in scripts/CI (wait until healthy)
- [ ] Explicit ports documented in README
- [ ] `make up/down/migrate/seed/test/ci` (or equivalent) is canonical and documented

---

## Phase 2: Data Model (Lock semantics before code)
(Claimed done; verify via RG2 + schema tests)
- [x] Object model docs
- [x] State DB schema spec
- [x] Ledger DB schema spec
- [x] Security and visibility spec

NEW REQUIRED:
- [ ] Confirm the implementation matches docs (schema drift test in CI)

---

## Phase 3: Event Envelope + Contracts
(Claimed done; verify via contract validation tests)
- [x] Event envelope definition includes event_version/contract_version/idempotency_key
- [x] Intervention registry spec
- [x] Domain tags spec

NEW REQUIRED:
- [ ] Contract schema tests in CI:
  - [ ] invalid envelope rejected
  - [ ] unknown action_type rejected + SYSTEM_WARNING logged

---

## Phase 4: Migrations + Seed Data
### 4.0 Implement migrations
- [x] Create migration toolchain
- [x] Implement State DB schema
- [x] Implement Ledger DB schema
- [x] Add indexes

### 4.1 Seed a demo campaign
- [ ] Create sessions table OR equivalent canonical session record (REQUIRED)
- [ ] Seed must create:
  - [ ] campaign
  - [ ] session row
  - [ ] principals
  - [ ] entities (2 PCs, 1 NPC)
  - [ ] one map room
  - [ ] encounter template
- [ ] Seed prints IDs and writes a “smoke join token” for DM and Player

Acceptance:
- RG1 can be executed from seed output alone.

---

## Phase 5: Deterministic Engines (Mechanics + Spatial)
(Claimed done; must be proven by deterministic tests)
- [x] Mechanics endpoints + tests
- [x] Spatial endpoints + tests

NEW REQUIRED:
- [ ] Integration test: Orchestrator calls mechanics + spatial and commits deltas atomically

---

## Phase 6: Orchestrator/Router Core
(Claimed done; must be proven end-to-end)
- [x] REST + WebSocket interfaces
- [x] COMBAT loop
- [x] Validation pipeline
- [x] Concurrency + idempotency

NEW REQUIRED:
- [ ] “Unknown action_type” rejection writes SYSTEM_WARNING ledger entry (assert in integration test)
- [ ] Encounter/session locks proven by concurrency test

---

## Phase 7: Visibility Enforcement End-to-End
(Claimed done; must be proven with hard tests)
- [x] Ledger writes include visible_to[]
- [x] Context assembly filtering

NEW REQUIRED:
- [ ] WebSocket broadcast filtering test (server-side filtering, not client filtering)

---

## Phase 8: LLM Adapter Layer (Text Only)
(Claimed done; add CI-safe mode)
- [x] LLM adapter
- [x] DM agent narration only
- [x] NPC agent directed only

NEW REQUIRED:
- [ ] MockLLM adapter mode for CI and local dev:
  - [ ] no external inference calls
  - [ ] deterministic fixture proposals and dialogue

---

## Phase 9: Schrödinger’s Conversation
(Claimed done; verify token discipline)
- [x] Olympus loop
- [x] On-screen proximity
- [x] Off-screen simulation deltas only

NEW REQUIRED:
- [ ] Test: off-screen simulation produces no LLM calls (assert call count = 0)

---

## Phase 10: Karma + Divine Standing
(Claimed done; verify thresholds)
- [x] Tag stamping
- [x] Standing updates
- [x] Threshold wakes

NEW REQUIRED:
- [ ] Test: threshold wake triggers only on crossings, not on every tagged event

---

## Phase 11: Divine System
(Claimed done; verify ordering)
- [x] Equal AP + caps
- [x] Authority + override order rules
- [x] Grudges

NEW REQUIRED:
- [ ] Integration test: elder-first then minor-second effect sticks until countered (ordering proof)

---

## Phase 12–16: NPC, Social, Guilds, Economy, Content
(Claimed done; verify consequence chains and toggles)
NEW REQUIRED:
- [ ] Campaign toggles integration tests (content mode, divine enabled/disabled, etc.)
- [ ] Murder-hobo consequence smoke test from RG1 (kill villager → bounty/investigation event)

---

## Phase 17: Maps
(Claimed done; must prove in RG1)
NEW REQUIRED:
- [ ] “Map truth” test:
  - [ ] collision mask blocks movement server-side
  - [ ] UI reflects blocked move as rejection

---

## Phase 18: Frontend MVP
(Claimed done; must prove in RG1)
NEW REQUIRED:
- [ ] Two-client test harness (DM + Player) for WS feed differences (visible_to proven)

---

## Phase 19: Export + Replay + Debugging
(Claimed done; must prove state reproduction)
NEW REQUIRED:
- [ ] Replay test:
  - [ ] checkpoint + ledger replay reproduces state exactly OR fails loud with diff output

---

## Phase 20: Hardening + Ops
(Claimed done; CI proves it)
NEW REQUIRED:
- [ ] CI uses canonical scripts (`scripts/test.sh` or `make ci`)
- [ ] CI executes RG-lite smoke:
  - [ ] /health OK
  - [ ] migrations OK
  - [ ] seed OK
  - [ ] 1 proposal → tool call → delta → ledger append

---

## Burn Bag (Optional but you requested it)
- [ ] Create `burn-bag/` for temporary smoke tests only
- [ ] Permanent unit/integration tests stay in normal test folders

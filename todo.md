# TODO: Headless Multi-Agent AI VTT Engine (Ship Sequence)
Rule: follow the Mandatory Build Order. No re-architecture. No shortcuts.

---

## Build Order Snapshot (Canonical)
1. Contracts + schemas (`shared/schemas`, `docs/*contract*`).
2. DB migrations and seed (`infra/sql/migrations`, `infra/sql/seed`).
3. Deterministic engines (`services/mechanics`, `services/spatial`).
4. Orchestrator pipeline (`services/orchestrator`).
5. Visibility + ledger enforcement (`services/visibility`, `services/ledger`).
6. Domain systems (social, karma/divine, NPC/maps/content).
7. UI + WebSocket consumption (`templates`, `static`).
8. CI gates (`.github/workflows/ci.yml`, `make ci`).

## Feature Gates
- **Playable now:** deterministic mechanics/spatial, orchestrator proposal pipeline, append-only ledger, visibility-filtered broadcasts, seeded campaign, web UI map/feed/console, CI lint/type/unit/contracts/integration.
- **In-progress/next:** richer map authoring UX, broader scenario seeds, expanded replay/debug tooling ergonomics.

## Known Limitations + Next Priorities
- Start scripts currently target Docker-first local setup; manual non-Docker flow is secondary.
- Integration coverage focuses on schema/visibility/migration paths; add full multi-client combat round automation next.
- Content and divine systems are contract-bound but should gain more balancing fixtures in tests.

---


## Phase 0: Repo + Contracts
### 0.0 Create repo structure
- [x] Create /infra, /services/*, /frontend, /docs
- [x] Add README.md (from this repo)
- [x] Add TODO.md (this file)
- [x] Add /docs placeholders:
  - [x] SPEC_MASTER.md
  - [x] DATA_MODEL.md
  - [x] STATE_DB_SCHEMA.md
  - [x] LEDGER_SCHEMA.md
  - [x] EVENT_ENVELOPE.md
  - [x] INTERVENTION_CONTRACT.md
  - [x] DOMAIN_TAGS.md
  - [x] SECURITY_VISIBILITY.md
  - [x] CONTENT_RATING.md
  - [x] REPLAY_DEBUG.md

Acceptance:
- Repo boots with no code yet; docs exist; no ambiguity in naming.

---

## Phase 1: Infra (Docker)
### 1.0 Docker compose for dependencies
- [x] Postgres (State + Ledger; separate schemas or separate DBs)
- [x] Redis (pubsub + presence + job queues)
- [x] Qdrant (vector DB)
- [x] Add env.example with all required vars

Acceptance:
- `docker compose up` starts cleanly
- Health checks pass
- Can connect with psql, redis-cli, and Qdrant health endpoint

---

## Phase 2: Data Model (Lock semantics before code)
### 2.0 Write canonical object definitions
- [x] Principal vs Entity rules
- [x] Campaign/Session/Encounter hierarchy
- [x] Mode state machine rules
- [x] Controlled_By handoff semantics

Acceptance:
- DATA_MODEL.md defines every term once.

### 2.1 State DB schema spec
- [x] campaigns, principals, campaign_members
- [x] entities (universal sheet: tags, public_sheet, secret_sheet, typed perf fields)
- [x] spatial: maps, map_nodes (tier), collision masks, terrain chunks
- [x] encounters, encounter_slots (initiative), conditions
- [x] intents, reactions (combat/social)
- [x] interventions (active blessings/curses with authority and stack rules)
- [x] divine standings (player↔god)
- [x] reaction_triggers (pre-registered AI reactions)
- [x] factions/guilds, membership, bounties, wars
- [x] economy: locations metrics, shops, inventory, price modifiers, property ownership

Acceptance:
- STATE_DB_SCHEMA.md lists columns, PK/FK, indexes, and constraints.

### 2.2 Ledger DB schema spec
- [x] session_ledger append-only table with:
  - [x] event_id, event_version, type, sender, payload
  - [x] visible_to[] of principal UUIDs
  - [x] trace fields: parent_event_id, domain_tags, contract_version
- [x] session_summaries table (visibility scoped)
- [x] redaction overlay mechanism (append-only redaction events)

Acceptance:
- LEDGER_SCHEMA.md includes replay expectations and RLS/filter approach.

### 2.3 Security and visibility enforcement spec
- [x] Define how `visible_to` is assigned
- [x] Define DM-only, gods-only, party-only, telepathy scopes
- [x] Define DB-level enforcement strategy:
  - [x] RLS using `app.principal_id` OR
  - [x] mandatory query filters in data layer
- [x] Define how services authenticate principals

Acceptance:
- SECURITY_VISIBILITY.md describes enforcement and test plan.

---

## Phase 3: Event Envelope + Contracts
### 3.0 Event envelope definition (single canonical format)
- [x] EVENT_ENVELOPE.md: JSON schema, event types, examples
- [x] Must include: event_version, contract_version, idempotency_key

Acceptance:
- Every system uses the same envelope and types.

### 3.1 Intervention contract registry spec
- [x] INTERVENTION_CONTRACT.md registry:
  - [x] action_type allowlist
  - [x] strict params per action_type
  - [x] who can propose
  - [x] who can commit
  - [x] deterministic tool mapping target
  - [x] stacking rules and override rules
  - [x] visibility defaults per action
  - [x] AP costs and caps policy hooks

Acceptance:
- No action exists without registry entry and deterministic mapping.

### 3.2 Domain tags taxonomy spec
- [x] DOMAIN_TAGS.md: canonical tags + examples + routing implications
- [x] Weight mapping config structure (tag→delta) per god/faction

Acceptance:
- Every STATE_DELTA emits tags from this list only.

---

## Phase 4: Migrations + Seed Data
### 4.0 Implement migrations
- [x] Create migration toolchain
- [x] Implement State DB schema
- [x] Implement Ledger DB schema
- [x] Add indexes (GIN for arrays, compound indexes for campaign/time, etc.)

Acceptance:
- `make migrate` or equivalent fully bootstraps DB from scratch.

### 4.1 Seed a demo campaign
- [x] Create campaign (session tracking is a uuid reference; no sessions table yet)
- [x] Create principals: DM, PlayerA, PlayerB, God1, NPCAgent
- [x] Create entities: 2 PCs, 1 NPC, 1 map room
- [x] Create an encounter template for testing

Acceptance:
- Seed script prints IDs and a ready-to-run test scenario.

---

## Phase 5: Deterministic Engines (Mechanics + Spatial)
### 5.0 Mechanics Engine service
Implement deterministic endpoints (strict schemas):
- [x] roll_dice (crypto RNG; log breakdown)
- [x] update_hp
- [x] apply_condition / remove_condition
- [x] modify_inventory
- [x] resolve_attack (hit check + damage)
- [x] resolve_save
- [x] compute_state_deltas output format

Rules:
- [x] No narration
- [x] Always returns deltas + roll logs + engine events

Acceptance:
- Unit tests validate deterministic results and audit logging structure.

### 5.1 Spatial Engine service
Implement deterministic endpoints:
- [x] move_entity (collision + max move validation)
- [x] compute_path (A*)
- [x] check_line_of_sight (raycast vs blockers)
- [x] threat_radius_triggers (opportunity triggers)

Acceptance:
- Unit tests on a small collision grid and LoS cases.

---

## Phase 6: Orchestrator/Router Core
### 6.0 Orchestrator skeleton
- [x] REST + WebSocket interfaces
- [x] Loads principal identity for each request
- [x] Provides “submit intent” endpoints
- [x] Streams events to clients

Acceptance:
- Can broadcast a CHAT event to a connected client.

### 6.1 Mode + encounter loop
- [x] Implement mode state machine (GM-controlled)
- [x] Implement COMBAT loop:
  - [x] turn start → controlled_by gate
  - [x] intent window
  - [x] reaction stack LIFO
  - [x] deterministic tool calls
  - [x] commit deltas
  - [x] write ledger events
  - [x] broadcast filtered results

Acceptance:
- Full encounter can complete with two PCs vs one NPC.

### 6.2 Validation pipeline (hard reject hallucinations)
Implement the synchronous pipeline:
- [x] schema validation
- [x] auth/resource check (AP, permissions, contract allowlist)
- [x] authority/override check (divine conflicts)
- [x] translation to tool calls
- [x] transactional commit:
  - [x] state updates + AP deductions
  - [x] ledger append(s)
- [x] broadcast

Acceptance:
- Invalid proposal causes:
  - no state mutation
  - SYSTEM_WARNING ledger entry
  - observable error response

### 6.3 Concurrency + idempotency
- [x] Encounter/session locks on commit
- [x] Idempotency keys for proposals and commits
- [x] Retry-safe tool application

Acceptance:
- Resending the same proposal does not double-apply deltas.

---

## Phase 7: Visibility Enforcement End-to-End
### 7.0 Ledger writes always include visible_to[]
- [x] DM-only events
- [x] gods-only events
- [x] party-only events
- [x] telepathy pair events

### 7.1 Context assembly filtering
- [x] Agent context queries return only visible events for that principal

Acceptance:
- Tests prove player cannot retrieve DM-only content even via direct API calls.

---

## Phase 8: LLM Adapter Layer (Text Only)
### 8.0 LLM adapter
- [x] Direct HTTP calls to inference server
- [x] Structured output mode for proposals (JSON schema validation)
- [x] Timeouts, retries, circuit breaker
- [x] Token budgeting hooks

Acceptance:
- LLM output that fails schema is rejected and logged.

### 8.1 DM agent (narration only)
- [x] Input: visible deltas + cited RAG chunks (optional)
- [x] Output: NARRATION event only

### 8.2 NPC agent (directed proximity only)
- [x] Triggered only when a human can hear it
- [x] Uses emotional state + local context
- [x] Output: DIALOGUE event only

Acceptance:
- NPC dialogue never runs off-screen.

---

## Phase 9: Schrödinger’s Conversation
### 9.0 Olympus loop (gods chat)
- [x] Pub/Sub subscription to committed STATE_DELTA
- [x] Gods chat is event-driven, not constant
- [x] Logged as gods-only visibility

### 9.1 On-screen proximity chat
- [x] Room/chunk subscriptions
- [x] Directed chat requests
- [x] Ambient barks from cache/scripted list (no LLM)

### 9.2 Off-screen simulation
- [x] Off-screen interactions generate only typed state deltas
- [x] Dialogue lazy-load when asked

Acceptance:
- Token usage stays stable with large NPC population.

---

## Phase 10: Deterministic Karma Router + Divine Standing
### 10.0 Domain tag stamping
- [x] Mechanics engine stamps domain_tags onto STATE_DELTA events
- [x] Enforce taxonomy allowlist

### 10.1 Standing updates (no LLM)
- [x] Update Player↔God standings deterministically from tags
- [x] Write updates as state deltas + ledger

### 10.2 Threshold wakes (LLM only on boiling points)
- [x] Threshold config (±10, ±50, etc.)
- [x] When crossed, wake specific god agent with last 5 relevant deltas
- [x] God agent returns an Intervention Proposal (schema locked)

Acceptance:
- Gods remain quiet until threshold crossings.

---

## Phase 11: Divine System (Equal AP, Authority Overrides, Grudges)
### 11.0 Divine AP system
- [x] Equal AP pools and regen for all gods
- [x] Per-encounter and per-session global caps

### 11.1 Authority system
- [x] Authority rank gates intervention tier and effect magnitude
- [x] Override rules:
  - [x] Elder can erase minor only if acting after and spending AP
  - [x] If elder acted first, minor action can stick unless later countered

### 11.2 Grudges + factions
- [x] Countered interventions increase rivalry
- [x] Gods form factions and coordinate in Olympus chat
- [x] Still bounded by AP and contract

Acceptance:
- Ordering tests confirm “thousand cuts” balance dynamic.

---

## Phase 12: NPC Persistence + Consequence Engine
### 12.0 Seeded NPC population and instantiation
- [x] Location seeds
- [x] Instantiate NPCs on first interaction
- [x] Persist individuals forever

### 12.1 Death tracking
- [x] Record killer, location, time, cause, witnesses
- [x] Emit consequences:
  - [x] investigation
  - [x] bounties
  - [x] faction hostility shifts
  - [x] rumor propagation
  - [x] economy modifiers
  - [x] divine tag triggers

Acceptance:
- Murder hobo causes systemic fallout without DM manual intervention.

---

## Phase 13: Social System + Ambush
### 13.0 SOCIAL mode implementation
- [x] Tension ladder state deltas
- [x] Deterministic social checks
- [x] De-escalation and escalation triggers

### 13.1 Ambush pipeline
- [x] Stealth intent + awareness checks
- [x] Surprise rules
- [x] GM commits COMBAT mode transition explicitly

Acceptance:
- Talking can prevent fights; ambush can start fights.

---

## Phase 14: Guilds/Factions/Patrons
### 14.0 Guild and faction mechanics
- [x] Create/join/raid guilds
- [x] Membership gates
- [x] Internal politics metrics
- [x] War declarations and retaliation

### 14.1 Patron/tenet enforcement
- [x] Tenet templates
- [x] Violations cause:
  - [x] REVOKE_SPELL_ACCESS
  - [x] APPLY_CURSE
  - [x] SET_BOUNTY
- [x] All toggleable via campaign rules

Acceptance:
- Priest killing triggers enforcement deterministically.

---

## Phase 15: Economy + Property
### 15.0 Reactive pricing
- [x] Location metrics drive multipliers
- [x] War + demon control + scarcity + reputation affects prices and stock

### 15.1 Property system
- [x] Buy property
- [x] Income/upkeep cycle
- [x] Raid risk tied to stability and reputation

Acceptance:
- War town makes potions expensive; demon region makes human goods expensive.

---

## Phase 16: Content Rating Gate
### 16.0 Content mode enforcement
- [x] SAFE / MATURE / EXPLICIT
- [x] Enforced at generation and pre-broadcast
- [x] Hard blocks always:
  - [x] minors
  - [x] non-consensual sexual content

Acceptance:
- Attempted disallowed content is blocked and logged as SYSTEM_WARNING.

---

## Phase 17: Maps
### 17.0 Upload 2D maps
- [x] Asset upload storage
- [x] Grid mapping + scale
- [x] Collision mask authoring stub (manual tool later)
- [x] Server-side movement validation

### 17.1 Procedural voxel maps
- [x] Backend seed + chunk data + blockers
- [x] Destruction as deltas
- [x] Frontend renders from seed, never authoritative

Acceptance:
- Player movement is server-valid only.

---

## Phase 18: Frontend MVP
### 18.0 Event feed (Narrative Board)
- [x] WebSocket client
- [x] Threaded feed rendering
- [x] Redactions respected

### 18.1 Command console
- [x] Slash commands
- [x] Structured intent builder for move/attack/cast/talk
- [x] Reaction window UI

### 18.2 three.js map viewer
- [x] Render tokens from backend XYZ
- [x] Map scale switching (world/region/city/room)
- [x] Apply deltas only

Acceptance:
- UI is a viewer; backend is truth.

---

## Phase 19: Export + Replay + Debugging
### 19.0 Export
- [x] Export session ledger to Markdown (visibility filtered)
- [x] Optional PDF

### 19.1 Replay
- [x] Load checkpoint
- [x] Replay deltas from ledger
- [x] Verify state matches current truth or fail loud

Acceptance:
- Replay mismatch produces a deterministic diff report.

---

## Phase 20: Hardening + Ops
### 20.0 Observability
- [x] trace_id everywhere
- [x] metrics: turn duration, tool latency, LLM latency, token count
- [x] health endpoints

### 20.1 CI
- [x] lint + unit tests + integration tests
- [x] schema validation tests for contracts
- [x] docker compose smoke test

Acceptance:
- CI fails on any deterministic or visibility regression.

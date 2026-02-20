# Headless Multi-Agent AI-Driven VTT Engine
Production-oriented, headless VTT + RPG engine with deterministic state, append-only event ledger, strict visibility filtering, and multi-agent LLM layer (DM, NPCs, Gods, Factions) that can only propose schema-validated actions.

## 1) Prime Directives (Non-Negotiable)
- **LLMs are text engines only.**
  - No dice, no math, no inventory truth, no spatial truth, no direct state mutation.
  - LLM outputs must be schema-validated proposals or narration/dialogue.
- **Deterministic backend is law.**
  - Mechanics, RNG, spatial logic, and state transitions are server-side only.
- **One Path to Reality (no shortcuts):**
  - `Proposal → Schema Validation → Auth/Resource Check → Tool Call → State Delta → Ledger Event → Broadcast`
- **Append-only Ledger.**
  - Ledger is the audit trail and replay source. Never updated, only appended.
  - State DB is mutable current truth.
- **Visibility enforced at the data layer.**
  - Every ledger record has `visible_to[]` (principal IDs).
  - Reads for context and broadcasts are filtered by `visible_to[]`. No exceptions.
- **Idempotent commits.**
  - All proposals/commits use `idempotency_key`. Retries must not double-apply deltas.
- **Schema versioning required.**
  - Every event envelope and intervention proposal carries `event_version` / `contract_version`.

## 2) High-Level Architecture (Headless First)

### Data Pillars
- **State DB (Postgres):** canonical world truth
  - entities (universal stat sheets), stats, inventory, coordinates, factions/guilds
  - economy metrics, divine standings, interventions, pre-registered triggers
- **Ledger DB (Postgres, append-only):**
  - event envelopes, tool calls/results, intents, reactions, deltas, narration/dialogue
  - every row includes `visible_to[]` (principal IDs)
- **Vector DB (Qdrant or equivalent):**
  - RAG knowledge: rules/lore chunks with citations + stable IDs
  - runtime use: reference only, never state authority

### Backend Services
- **Orchestrator/Router:** mode switching, turn loop, intent windows, reaction stack, arbitration, commits, broadcast
- **Mechanics Engine:** deterministic dice, HP/resources, conditions, combat resolution, inventory updates
- **Spatial Engine:** A*, LoS raycasts, threat radius triggers, movement validation
- **Pantheon Service:** gods chat loop + gods intervention proposals (AP-gated, contract-bound)
- **Faction/Guild Service:** membership rules, expulsion, raids, wars, bounties, political proposals
- **Economy/Property Service:** supply/demand, scarcity, price multipliers, shop stock, property ownership/upkeep
- **Karma/Reputation Router:** deterministic scoring from `domain_tags` → standings → threshold wake triggers
- **Summarizer:** compresses ledger into summaries to control context window size
- **Content Rating Gate:** global SAFE/MATURE/EXPLICIT enforcement at generation and broadcast

## 3) Canonical Object Model
- **Principal:** actor/viewer identity (human player, DM agent, god agent, NPC agent). Defines visibility + permissions.
- **Entity:** thing in the world (PC/NPC/monster/object/location/faction/god). Has stats and state.
- **Control handoff:** each entity has `controlled_by` and `controller_principal_id`.

Hierarchy:
- **Campaign:** persistent container
- **Session:** play instance; produces summaries + checkpoints
- **Encounter:** combat instance with initiative + rounds

Mode state machine (GM-controlled):
- `EXPLORATION → SOCIAL → COMBAT → CUTSCENE → PAUSED`
- Combat does NOT auto-trigger; requires explicit mode transition.

## 4) Universal Entity Sheets (ECS Style)
- Single `entities` model: PCs/NPCs/gods/items/locations/factions all represented as entities.
- Stats stored as:
  - typed columns for perf-critical fields (hp, ac, speed, etc.)
  - JSON sheets for flexible components
- Mechanics engine treats conflicts uniformly:
  - dragon burning city = damage against city stability/hp → 0 triggers RUINED state.

## 5) RAG-to-World Pipeline
- **Offline only:** Extract templates from RAG into State DB (race/creature/deity/location/faction templates).
- **Runtime:** RAG provides citations and lore flavor; never determines combat math or state.

## 6) Event Envelope (Universal Log + Stream Atom)
All events are a single envelope with:
- ids: campaign/session/encounter
- sender: principal_id (+ optional entity_id)
- type: CHAT/OOC/INTENT/REACTION/TOOL_CALL/TOOL_RESULT/STATE_DELTA/NARRATION/SYSTEM
- payload: typed structured data (no mechanical prose)
- visibility: `visible_to[]` principal IDs
- trace: parent_event_id, tags, domain_tags, event_version

## 7) Intervention Contract
Agents can only output proposals from a hard allowlist with strict parameters.
- Unknown action types are rejected.
- Contract is versioned and registry-driven.

## 8) Validation Pipeline
Orchestrator must:
1) schema validate
2) auth/resource check (AP, permissions)
3) authority/override check
4) translate to deterministic tool calls
5) commit transaction (state + ledger append)
6) broadcast filtered events

## 9) Combat Latency Fix: Pre-Registered Triggers
AI entities register deterministic reaction triggers:
- ON_MOVEMENT (opportunity attack)
- ON_ATTACKED (shield)
- ON_CAST (counterspell)
Executed with zero LLM calls.

## 10) Context Assembler
Agent prompts built from:
- State DB query
- Ledger query filtered by visible_to
- Optional Vector DB retrieval (top-k)
Injected as JSON blocks to reduce token cost.

## 11) Schrödinger’s Conversation
Three pipelines:
- **Olympus:** gods-only chat, event-driven
- **On-screen:** proximity + directed dialogue, high fidelity
- **Off-screen:** simulation deltas only; dialogue lazy-loaded later

## 12) Deterministic Karma Router
- All committed state deltas include `domain_tags`
- Router updates standings deterministically
- LLM wakes only on threshold crossings

## 13) Divine System Rules
- Equal AP pools for all gods
- Authority controls effect tier and override ability
- Order-of-ops matters for overrides
- Hard caps per encounter/session
- Grudges/factions tracked on counters/erasures

## 14) NPC Consequence Engine
- Seeded procedural population → instantiate on interaction → persist forever
- Death is first-class (killer, location, time, witnesses)
- Murder-hobo consequences: investigations, bounties, retaliation, rumors, economy shifts, divine response

## 15) Social System
- Formal SOCIAL mode with tension ladder:
  - CALM → SUSPICIOUS → HOSTILE → WEAPONS_DRAWN → COMBAT
- Ambush is structured; GM commits combat

## 16) Guilds/Patrons/Faction Membership
- Join/create/raid guilds
- Tenet enforcement: revoke spell access, curses, bounties (toggleable)
- Gods can bless/curse non-followers within contract

## 17) Economy + Property
- Location metrics drive prices and availability
- Property ownership: income/upkeep/raid risk tied to stability and reputation

## 18) Content Controls
Modes:
- SAFE (PG-13)
- MATURE (fade-to-black)
- EXPLICIT (adult allowed with consent flags)
Hard blocks always:
- minors
- non-consensual sexual content
Enforced at generation and pre-broadcast.

## 19) Maps
Backend owns truth; frontend renders.
- Upload 2D maps with grid + collision masks
- Procedural voxel maps from seed + chunk deltas
Hybrid supported.

## 20) Session Lifecycle
States:
- DRAFT → ACTIVE → PAUSED → ENDED → ARCHIVED → TOMBSTONED → PURGED
Checkpoints:
- session start/end, encounter start, end of round, manual GM save
Supports restart, fork, tombstone, purge (policy gated).

## 21) Mandatory Build Order
1) DB schemas + Event Envelope
2) Mechanics + Spatial deterministic tools (tests)
3) Orchestrator loops + validation + commits
4) Minimal UI (feed + console + map viewer)
5) Summarizer
6) NPC persistence + Social + Consequences
7) Karma Router + thresholds
8) Guild/Faction system
9) Economy/Property system
10) Pantheon chat + divine interventions (last)

## 22) Open Blockers (must resolve before production lock)
- Authority rank model: fixed vs myth-event changes
- Domain tag taxonomy + weights per deity/faction
- Social mechanics depth: DC vs social combat pool
- Map collision authoring: manual paint vs auto-inference
- Intervention Contract Registry: required artifact (no registry, no agents)

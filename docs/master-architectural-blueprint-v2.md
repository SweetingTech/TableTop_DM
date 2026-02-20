# 1. Prime Directives
- **LLMs are text engines only**.
  - They do not perform authoritative math.
  - They do not roll or resolve dice.
  - They do not own inventory truth.
  - They do not own spatial truth.
  - They do not mutate persistent state.
- **Deterministic backend is law**.
  - Mechanics, resolution, and persistence execute only in backend services.
- **Single path to reality** is mandatory for every world mutation.
  - `Proposal → Validation → Tool Call → State Delta → Ledger Event → Broadcast`
- **Ledger is append-only**.
  - Ledger rows are never updated or deleted during normal operations.
  - Replay reconstructs historical truth from ordered ledger events.
- **State DB is mutable truth**.
  - Current canonical values for entities, resources, and world metrics reside in State DB.
- **Visibility is enforced at data level**.
  - Every ledger record includes `visible_to[]` principal IDs.
  - Delivery systems filter by `visible_to[]` before any transmission.

# 2. High-Level Architecture (Headless-First)
- **Data Pillar 1: State DB (Postgres)**
  - Stores canonical current-world truth.
  - Domains:
    - entities and component sheets
    - combat and derived stats
    - inventory and ownership
    - coordinates and spatial occupancy
    - factions and guild membership
    - economy metrics per location
    - divine standing and intervention counters
    - pre-registered reaction triggers
- **Data Pillar 2: Session Ledger (Postgres, append-only)**
  - Stores immutable event envelopes in strict order.
  - Stores tool call intents and tool results.
  - Stores state deltas and narrated outputs.
  - Every row carries `visible_to[]` and is filtered per principal before delivery.
- **Data Pillar 3: Vector DB (Qdrant or equivalent)**
  - Stores indexed rule and lore chunks with citations and stable IDs.
  - Runtime role is reference-only.
  - Runtime decisions never depend on uncommitted vector text.
- **Backend Services**
  - **Orchestrator / Router**
    - validates proposals, routes actions, commits accepted deltas.
  - **Mechanics Engine**
    - deterministic rules, dice, effects, damage, checks, AP accounting.
  - **Spatial Engine**
    - deterministic movement, line-of-sight, proximity, collision, instancing.
  - **Pantheon Service**
    - deity AP pools, authority tiers, intervention throttles, rivalry signals.
  - **Faction/Guild Service**
    - membership rules, hierarchy changes, political state transitions.
  - **Economy/Property Service**
    - market metrics, scarcity effects, property income/upkeep/raid exposure.
  - **Karma/Reputation Router**
    - domain-tag fan-out and standing updates via fixed weight tables.
  - **Summarizer**
    - principal-scoped compression of ledger windows into resumable summaries.
  - **Content Rating Gate**
    - enforces SAFE/MATURE/EXPLICIT policy and hard prohibitions.

# 3. Canonical Object Model
- **Principal vs Entity**
  - **Principal**: authenticated actor or viewer identity.
    - player principal
    - DM principal
    - god agent principal
    - NPC agent principal
  - **Entity**: world object with simulation state.
    - PC, NPC, monster, object, location, faction, god
  - **Control handoff contract on every controllable entity**
    - `controlled_by` indicates control mode.
    - `controller_principal_id` identifies active controlling principal.
- **Campaign / Session / Encounter**
  - **Campaign**: persistent world container across many sessions.
  - **Session**: bounded play instance that emits summaries and checkpoints.
  - **Encounter**: combat-scoped instance tracking initiative, rounds, and combat timers.
- **Mode State Machine (GM-controlled)**
  - Allowed modes:
    - `EXPLORATION`
    - `SOCIAL`
    - `COMBAT`
    - `CUTSCENE`
    - `PAUSED`
  - Transition authority:
    - GM principal commits mode transitions through orchestrator.
  - Combat trigger rule:
    - damage events alone never force `COMBAT`.
    - explicit mode transition is required.

# 4. Universal Entity Sheets (ECS Architecture)
- **Single ECS substrate for all world objects**
  - PCs, NPCs, monsters, animals
  - gods and avatars
  - locations and landmasses
  - factions and guilds
  - items
  - hazards and world events as extension entities
- **Storage model**
  - One entity table/model in State DB.
  - Components represented as typed JSON sheets.
  - Performance-critical values mirrored in typed columns for indexed queries and deterministic hot loops.
- **Uniform conflict resolution**
  - Mechanics Engine evaluates interactions by component capability, not narrative class labels.
  - Example invariant:
    - location has stability component and defense component.
    - dragon attack applies deterministic damage to location stability.
    - stability reaching zero commits `RUINED` transition.

# 5. RAG-to-World Pipeline
- **Offline extraction path**
  1. Ingest lore, rules, and homebrew corpora into Vector DB.
  2. Run Offline Extraction Agent to transform text into deterministic templates.
     - race templates
     - creature templates
     - faction templates
     - deity templates with domains, authority, preferences
     - location templates with defaults and tags
  3. Persist extracted templates into State DB as authoritative runtime assets.
- **Runtime role of RAG**
  - Supplies rules references for explanations.
  - Supplies lore flavor for narration.
  - Supplies citations for player-facing rationale.
  - Never supplies authoritative combat math.
  - Never supplies authoritative state mutation decisions.

# 6. Event Envelope (Universal Log and Stream Format)
- **Event envelope is mandatory for ledger and stream transport.**
- Required fields:
  - campaign_id
  - session_id
  - encounter_id (nullable)
  - sender
    - principal_id
    - entity_id (nullable)
  - type
    - CHAT
    - OOC
    - INTENT
    - REACTION
    - TOOL_CALL
    - TOOL_RESULT
    - STATE_DELTA
    - NARRATION
    - SYSTEM
  - payload
    - typed structured fields only
    - no mechanical prose in authoritative payloads
  - visible_to[]
    - array of principal IDs
  - trace
    - parent_event_id
    - domain_tags

```json
{"campaign_id":"cmp_42","session_id":"ses_9","encounter_id":null,"sender":{"principal_id":"prn_dm","entity_id":null},"type":"STATE_DELTA","payload":{"delta_type":"HP_CHANGE","entity_id":"ent_ogre","amount":-7},"visible_to":["prn_dm","prn_p1"],"trace":{"parent_event_id":"evt_177","domain_tags":["combat","violence"]}}
```

# 7. Intervention Contract (The Only Way Agents Act)
- **All agent actions must be Intervention Contract proposals.**
- Required proposal fields:
  - `action_type` from hard-coded allowlist only
  - `target_ids[]` containing entity UUIDs
  - typed `parameters` schema bound to action_type
  - `ap_cost`
  - `narrative_justification` for internal context only
- **Enforcement**
  - Non-allowlisted `action_type` is rejected immediately.
  - Orchestrator appends `SYSTEM_WARNING` to Ledger with trace linkage.
- **Exhaustive v1 allowlist**
  - APPLY_BLESSING
  - APPLY_CURSE
  - REMOVE_EFFECT
  - DISPEL_EFFECT
  - GRANT_TEMP_ABILITY
  - REVOKE_TEMP_ABILITY
  - GRANT_RESISTANCE
  - REVOKE_RESISTANCE
  - MODIFY_REPUTATION
  - MODIFY_KARMA
  - TRIGGER_RUMOR
  - SUPPRESS_RUMOR
  - SET_BOUNTY
  - INCREASE_BOUNTY
  - CLEAR_BOUNTY
  - TRIGGER_INVESTIGATION
  - CLOSE_INVESTIGATION
  - SPAWN_EVENT
  - RESOLVE_EVENT
  - FORCE_WEATHER
  - MODIFY_LOCATION_METRIC
  - APPLY_SCARCITY
  - REMOVE_SCARCITY
  - MODIFY_SHOP_STOCK
  - MODIFY_PRICES
  - GRANT_ACCESS
  - REVOKE_ACCESS
  - REVOKE_SPELL_ACCESS
  - RESTORE_SPELL_ACCESS
  - DECLARE_WAR
  - DECLARE_TRUCE
  - IMPOSE_EMBARGO
  - LIFT_EMBARGO
  - KICK_MEMBER
  - INVITE_MEMBER
  - PROMOTE_MEMBER
  - DEMOTE_MEMBER
  - TRIGGER_RAID
  - END_RAID
  - START_ENCOUNTER
  - END_ENCOUNTER
- **Intervention Contract Registry**
  - Separate artifact is required.
  - Registry defines for every action_type:
    - parameter schema
    - allowed proposers
    - committing service authority
    - stacking and override rules
    - default visibility policy
    - deterministic tool mapping

# 8. Orchestrator Validation Pipeline
- **Synchronous hard pipeline for all proposals**
  1. Schema validation
     - malformed proposals rejected immediately
     - append `SYSTEM_WARNING` with trace ID
  2. Auth and resource checks
     - AP balance validation
     - permission scope validation
     - action allowlist validation by principal type
  3. Authority and override checks
     - conflict detection against active effects and locks
     - override precedence enforcement
  4. Translation
     - proposal translated to deterministic tool calls
  5. Commit transaction
     - deduct AP
     - apply state deltas in State DB
     - append event envelope sequence to Ledger
  6. Broadcast
     - WebSocket fan-out filtered by `visible_to[]`

# 9. Combat Latency Fix: Pre-Registered Triggers
- **Zero-token reaction architecture**
  - AI-controlled entities register trigger rules in State DB.
  - Mechanics and Spatial engines emit deterministic trigger events.
  - Orchestrator performs deterministic trigger matching and tool execution.
  - No LLM invocation in trigger resolution path.
- **Required trigger classes**
  - `ON_MOVEMENT`
    - supports opportunity attack contracts.
  - `ON_ATTACKED`
    - supports defensive reaction contracts such as shield response.
  - `ON_CAST`
    - supports spell interruption contracts such as counterspell response.

# 10. Context Assembler (Token Discipline)
- **Deterministic context assembly pipeline**
  1. Query State DB
     - active stats
     - position
     - conditions
     - inventory summary
  2. Query Ledger
     - recent N events
     - strict `visible_to[]` filtering by requesting principal
  3. Query Vector DB conditionally
     - triggered only by mechanical keyword detection
  4. Inject context to model input
     - structured JSON blocks
     - no freeform prose bundles

# 11. Schrödinger’s Conversation (Three Chat Pipelines)
## 11A) Deity Chat — Olympus Loop
- Decoupled from spatial simulation.
- Wake-up source is event-driven triggers.
- Not executed as constant polling loop.
- Logged to gods-only visibility by default.
- DM visibility is optional via policy.
- Leakage path supports summarized omens for specifically authorized roles.

## 11B) On-Screen Chat — Proximity/Directed
- Generated only when a human principal is within hearing range.
- Scoped to spatial instance membership such as room or chunk.
- Directed player targeting can wake one specific NPC agent.
- Ambient barks use scripted or cached lines with zero runtime LLM tokens.

## 11C) Off-Screen Chat — Simulation Mode (Clarified)
- Off-screen interactions produce no generated dialogue.
- Resolution is fully deterministic inside Mechanics Engine.
- Required deterministic check inputs:
  - entity stats
  - standing values
  - location modifiers
  - current conditions
- Output is recorded as typed STATE_DELTA only.
  - rumor transfer
  - suspicion change
  - alliance shift
  - reputation delta
- Dialogue reconstruction can be generated later only on explicit player request using recorded STATE_DELTAs.

# 12. Deterministic Karma Router
- **Domain tagging requirement**
  - every committed STATE_DELTA receives canonical `domain_tags`.
- **Deterministic fan-out**
  - router applies static weight tables per deity and faction profile.
  - standing scores are updated without LLM participation.
- **Threshold wake policy**
  - god or faction agent wakes only when configured threshold crossings occur.
  - wake payload includes:
    - last five relevant STATE_DELTAs
    - restricted instruction to propose one contract action

# 13. Divine System
- **AP structure**
  - all gods use identical AP pool model and regeneration mechanics.
- **Authority rank gating**
  - rank determines allowed intervention tiers and magnitude ceilings.
- **Override dynamics (order-of-operations)**
  - elder deity can erase minor deity effect only when acting afterward and paying AP.
  - if elder acts first, minor effect remains valid unless later countered by a valid intervention.
- **Usage caps**
  - hard intervention caps enforced per encounter.
  - hard intervention caps enforced per session.
- **Grudge system**
  - countered or erased actions increment rivalry counters.
  - rivalry counters enable factional backstabbing opportunities.
  - all rivalry-driven actions remain AP-gated and contract-bound.

# 14. NPC Consequence Engine
- **Population lifecycle**
  - seed populations per location template.
  - instantiate entities on first interaction.
  - persist instantiated NPCs permanently unless explicitly tombstoned.
- **Death as first-class record**
  - required attributes:
    - victim_id
    - killer_id
    - location_id
    - timestamp
    - cause_code
    - witness_ids
- **Murder-hobo consequence chain**
  - investigation opening
  - bounty issuance or escalation
  - retaliation event generation
  - rumor propagation
  - local economy impact
  - divine response through karma threshold crossing

# 15. Social System
- **Formal SOCIAL mode ladder**
  - `CALM → SUSPICIOUS → HOSTILE → WEAPONS_DRAWN → COMBAT`
- **Social action outputs**
  - deterministic state deltas for:
    - emotional state
    - reputation shifts
    - rumor flags
    - escalation triggers
- **Ambush flow**
  - stealth intent submission
  - deterministic awareness checks
  - surprise rule determination
  - GM commits mode transition to `COMBAT`

# 16. Guilds, Patron Punishments, and Faction Membership
- **Guild and faction governance**
  - membership requirements
  - granted benefits
  - enforceable obligations
  - political state handling
  - raid and war lifecycle operations
- **Deed-based expulsion and punishment**
  - priest violating tenets triggers abandonment, access revocation, and curse action path.
  - rogue violating guild code triggers penalties and bounty pathways.
  - warlock missing tribute triggers escalating punishment tiers.
- **Cross-alignment interventions**
  - gods can bless or curse non-followers only through intervention contract.
  - content controls gate all output content regardless of target allegiance.

# 17. Economy and Property (Reactive Commerce)
- **Location economy metrics**
  - prosperity
  - stability
  - war_status
  - scarcity_tags
  - controlling_faction_id
- **Deterministic market reactions**
  - war status raises potion and armament pricing coefficients.
  - demon control raises human goods scarcity and pricing coefficients.
- **Property system**
  - purchase commits ownership record and capital deduction.
  - recurring income and upkeep execute on deterministic schedules.
  - profitability ties to stability and owner reputation.
  - raid risk increases with conflict and notoriety factors.

# 18. Content Controls
- **Content modes**
  - SAFE
  - MATURE
  - EXPLICIT
- **Mode effects**
  - narration filters by selected mode.
  - lust-domain outputs are constrained by selected mode.
- **Hard blocks with no override path**
  - any content involving minors
  - non-consensual sexual content depictions

# 19. Maps: Upload vs Procedural Generation
- **Backend owns map truth and validation.**
- **Procedural or voxel maps**
  - backend stores world seed.
  - backend stores blockers.
  - backend stores chunk graph.
  - backend stores destructible state.
  - frontend renders map and applies received deltas.
- **Uploaded 2D maps**
  - backend stores authoritative grid mapping.
  - backend stores coordinate transform mapping.
  - backend stores collision masks.
  - frontend renders textured plane only.
  - movement validation remains server-side.
- **Hybrid mode**
  - one campaign can combine uploaded sectors and procedural sectors under one coordinate authority.

# 20. Session Lifecycle
- **Session states**
  - DRAFT
  - ACTIVE
  - PAUSED
  - ENDED
  - ARCHIVED
  - TOMBSTONED
  - PURGED
- **Deletion policy**
  - purge is gated by policy checks and explicit authority.
  - delete defaults to tombstone state.
- **Checkpoint schedule**
  - session start
  - session end
  - encounter start
  - end of every round
  - manual GM save
- **Required operations**
  - start
  - pause
  - resume
  - soft restart
  - fork timeline
  - tombstone
  - purge

# 21. Build Order (Mandatory)
1. State DB plus Ledger schema plus Event Envelope definition
2. Mechanics plus Spatial deterministic tools with tests
3. Orchestrator loop covering modes, intent windows, reactions, and commits
4. Minimal UI including feed, console, and map viewer
5. Summarizer
6. NPC persistence plus Social system plus Consequence engine
7. Karma Router plus threshold wakes
8. Guild and Faction system
9. Economy and Property system
10. Pantheon chat plus divine interventions

# 22. Open Architectural Decisions (Production Blockers)
- **Authority rank model**
  - blocker decision: fixed hierarchy model or myth-event mutable hierarchy model.
- **Domain tag taxonomy and weights**
  - blocker decision: canonical domain tag set and per deity/faction weight mappings.
- **Social mechanics depth**
  - blocker decision: single DC resolution model or social combat pool model.
- **Map collision authoring model**
  - blocker decision: manual paint tool workflow or auto-inference workflow.
- **Intervention Contract Registry artifact**
  - blocker decision: finalize separate registry artifact containing action type definitions, parameter schemas, proposing systems, committing authority, stacking and override rules, and visibility defaults.

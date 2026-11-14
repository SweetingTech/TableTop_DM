# Autonomous campaign implementation checklist

Code review baseline: commit `9d5a26a`, 2026-11-10. This is a proposed implementation
backlog, not a description of released behavior. Unchecked items remain work or verification.
Existing foundations are identified separately; their presence does not establish an end-to-end flow.

Implementation tracking: [Orderly campaign board](http://jarvis:8080/b/tabletop-dm-autonomous-campaign).
Checked items mean locally implemented and verified; Orderly acceptance and live deployment are separate.

## Product contract

- The operator supplies world direction, gods, factions, cast, backstories, and story set pieces.
- The world advances independently of who is observing it or whether any human is playing.
- Humans can play solo with autonomous companions, play together with absent-player stand-ins,
  or leave the entire campaign running autonomously.
- A stand-in follows that player's demonstrated behavior with that character. Character card and
  player-written backstory provide the initial persona and fill gaps in observed behavior.
- Any in-world character can potentially join or leave the party. Ability, knowledge, resources,
  motives, and circumstances determine opportunities; arbitrary protagonist/class locks do not.
- Characters have no access to operator instructions, simulation machinery, controller handoffs,
  protection flags, or abandoned timelines. Human players may understand the game; their characters do not.
- An AI DM can execute natural-language operator instructions using the same world-management
  tools as a human DM, plus explicitly granted operator tools. It plans, acts, verifies, and reports.
- The operator can pause, return to a prior point, correct an outcome, and continue a revised history.
- Models propose typed actions. Authorized kernel code remains the only canonical mutation path.

## Existing code and verified gaps

| Area | Existing wiring | Gap established by inspection |
| --- | --- | --- |
| Character binding | A1 wires [roster selection](../frontend/src/features/dm/DungeonMasterPage.tsx) to authorized character lookup and assignment | Atomic binding/reassignment and removal semantics remain A2/A3 |
| Console | [Page](../frontend/src/features/game-console/GameConsolePage.tsx) refreshes authorized scenes after actions and renders observations once per source event | Cross-client updates, fixed Harborport map, and four-token slice remain A5/A6 |
| Commands | [Bus](../kernel/command_bus.py), [application](../kernel/application.py), [durable repository](../kernel/postgres_repository.py) | No connected autonomous campaign driver |
| Scheduling | [DeterministicScheduler](../kernel/scheduling.py) | In-memory queue; production call sites were not found; only its test imports it |
| Population | [Lifecycle](../population/lifecycle.py), [repository](../population/postgres.py) | Explicit transitions retain state; `world_step` is supplied by callers, not a world clock; no activity progression |
| Background process | [WorldEventProjector](../cognition/projector.py), [CLI](../main.py) | Projects existing events into minds; does not generate next actions |
| Decisions | [LayeredDecisionEngine](../cognition/engine.py), API `cognition_decide` | Caller supplies situation/actions; returns `committed: false`; API calls engine without a model provider |
| Personas | B1 adds distinct character/playtester purpose and [compiler](../persona/compilation/compiler.py) trait filtering | Trusted live context, authored character identity, and player-history imitation remain unfinished |
| Runtime assignment | [MindStore](../cognition/store.py), [durable minds](../cognition/postgres.py), entity runtime API | Assignment exists; presence, exclusive control, and safe handoff are not a complete flow |
| Experiments | [ApplicationBranchExecutor.execute](../experiments/executor.py) | Applies a single scenario intervention, returns `steps=1`; horizon metadata is not a live campaign loop |
| Factions/gods/quests | [Reputation](../domains/tabletop/factions/__init__.py), [blessing](../domains/tabletop/divine/__init__.py), [quest counter](../domains/tabletop/quests/__init__.py) | These commands do not constitute autonomous factions, divine agendas, or causally verified quest systems |
| History | [Snapshots](../kernel/snapshots.py), [replay](../kernel/replay.py), [branching](../kernel/branching.py) | Snapshots contain projections; replay applies committed deltas; neither provides complete campaign revision |
| Lore | [Lore indexes](../kernel/lore.py) | Search primitives exist; character-specific, timeline-safe retrieval must be wired and tested |

## Delivery order and dependencies

1. A: repair and verify the existing human play path.
2. B–C: establish character context boundaries and authoritative rules.
3. D–F: connect world time, offscreen activities, and autonomous character execution.
4. G–H: add player-history stand-ins, exclusive handoffs, and dynamic parties.
5. I: deliver complete checkpoints and revision before unattended long-running campaigns.
6. J–K: connect campaign setup, story direction, and temporary protection.
7. L: expose the tested services to the AI DM; read/inspect tools can land earlier.
8. M–N: complete operator UX, recovery, packaging, and acceptance journeys.

New modules below are proposed locations, not files already present. Keep `kernel/api/app.py`
as composition glue; reusable execution services must also work from workers and tests.

## A. Repair the current play path

- [x] A1 — Add a character selector and explicit Player/Co-DM choice to the DM roster UI.
  Wire [DM adapter](../frontend/src/features/dm/api.ts) to a typed membership payload including
  `character_id`; provide an authorized endpoint listing assignable characters for the selected user/world.
  Implemented in [Orderly task 1](http://jarvis:8080/b/tabletop-dm-autonomous-campaign/t/1).
  Existing members can also receive a character. Lookup returns assignment summaries only;
  assignment validates existence, owner, and world. Verified with service/UI tests, durable
  restart integration, and an isolated Chromium invite/update journey at desktop/mobile sizes.
- [ ] A2 — Make roster update, entity creation, character binding, and authority changes recoverable
  as one logical operation. Current API saves membership before binding completes. Cover missing
  live run, missing character, wrong owner/world, retry, reassignment, and partial failure.
- [ ] A3 — Define whether removing a member removes control, keeps an autonomous character,
  or only removes the human seat. Wire through [portal](../domains/tabletop/portal.py) and
  [identity grants](../identity/repository.py); never leave stale body control accidentally.
- [x] A4 — Refresh the scene after accepted actions, wait for the relevant observation projection
  boundary, and deduplicate pending versus persisted feed entries. Clear local state on world/viewpoint changes.
  Implemented with an authorized receipt cursor, bounded/cancellable polling, request-local durable
  observation reads, and an observation-only feed. Verified with delayed-projection/retry/scope
  regressions and a real built-SPA cookie session at desktop/mobile sizes. Failed reads retry GET
  without resubmitting accepted actions. A5 continuous cross-client synchronization remains open.
- [ ] A5 — Add version/cursor-based updates across clients, reconnect/resync, and out-of-order response
  protection. Start with bounded polling if appropriate; preserve perception-scoped reads.
- [ ] A6 — Replace fixed map metadata with world/zone presentation configuration; remove the four-token
  limit. Check [map positioning](../frontend/src/features/game-console/mapPosition.ts) against zone coordinates.
- [ ] A7 — Handle missing run/body, inspect-only viewpoints, unsupported commands, and stale versions
  with actionable UI states. Never present failed writes as successful demo actions.
- [ ] A8 — Acceptance: invite and bind a character, speak/move/attack, observe correct health/position
  from two authorized clients, switch viewpoints without mixed observations, and restart successfully.

## B. Separate character knowledge from player and operator knowledge

- [x] B1 — Add explicit character-persona and simulated-playtester purposes to persona contracts and
  compilation. Retain existing evaluation behavior; exclude GM trust, controls, onboarding, and
  interface preferences from in-world identity/context.
  Implemented locally in [Orderly task 3](http://jarvis:8080/b/tabletop-dm-autonomous-campaign/t/3):
  API purpose selection, inherited purpose on successor versions, core/world trait allowlist,
  legacy playtester identity/hash compatibility, and migration 004 purpose persistence/constraints.
  Character compilation seeds no player goals/relationships/interface capabilities. Live context,
  lore, situation text, and body/persona binding remain B2–B7; B1 alone does not establish secrecy.
- [x] B2 — Add validated character backstory, motives, values, bonds, secrets, and initial known facts
  to [character records](../domains/tabletop/portal.py) and the Player form/import adapter. Version
  the card/backstory and establish its link to persona, mind, and embodied entity without merging identities.
  Implemented: validated authored fields/build-edit-import controls, deterministic card hashes,
  migration 005 immutable private history with upgrade backfill, and explicit version-pinned
  CHARACTER persona/card/world-branch-run-body/mind bindings. Initial roster assignment creates
  a missing binding; edits and roster retries preserve it until an authorized CAS successor.
  Pinned self fiction enters trusted context; initial knowledge remains a separate authored claim.
  Baseline persona traits are card-seeded, not semantic inference or learned player imitation.
  Actual live decision execution remains B4/F and is not activated by this foundation.
- [ ] B3 — Introduce a trusted character-context builder under `cognition/`. Resolve current scene,
  mind, remembered testimony, known lore, and legal action candidates for one world/branch/entity.
  Reuse [scene](../domains/tabletop/spatial/scene.py), perception contracts, and mind repositories.
  Foundation implemented: shared scene service, read-only [context builder](../cognition/context.py),
  same-branch event/frozen-grant validation, grounded memories/beliefs, and authorized context reads.
  The HTTP context now supplies a versioned basic movement-attempt catalog through a trusted
  domain provider, gated by world capabilities/body control and perceived self state. Hidden
  obstacles never filter choices; submission still passes kernel validation. This item remains
  open: known lore, broader speech/combat/activity actions, and dependent-decision
  projection barriers still need wiring. This catalog alone does not activate autonomous decisions.
- [x] B4 — Wire `cognition_decide` and the autonomous runner to that builder. Keep externally supplied
  evaluation situations confined to explicit privileged/testing flows rather than trusting them for live minds.
  The caller-authored endpoint is now privileged playtester evaluation only and rejects CHARACTER
    personas. A trusted CHARACTER proposal endpoint now resolves pinned identity/context/actions,
    derives scoped server seeds, waits for sensory projection, and stores private append-only
    idempotent receipts plus traces atomically (006). It uses local basic movement utility policy,
    returns PROPOSAL_ONLY. A separate bounded runner now consumes that builder and submits fenced
    kernel commands after explicit controller handoff (007), with atomic step/budget accounting,
    observation readiness, concurrent retry/restart recovery, and player takeover. Caller-authored
    evaluation remains privileged playtester-only. Execution currently uses local basic movement
    utility; richer actions, narrative goals, the world clock, and history imitation remain F/G/D.
- [ ] B5 — Route lore retrieval, summaries, and model conversations through the same knowledge and
  timeline boundary. Public availability must not automatically mean a character has learned a fact.
- [ ] B6 — Label operator/director records outside the sensory event stream. Audit [event finalization](../kernel/event_factory.py),
  observations, prompts, receipts, and retrieval so revision notes/protection rules never become character evidence.
- [ ] B7 — Acceptance: seed hidden plot facts and abandoned-timeline facts; verify they cannot enter
  character context, speech, memory, or retrieval. Test god knowledge limits and human-player/character separation.

## C. Make action outcomes authoritative

- [ ] C1 — Replace caller-selected attack bonuses/dice with rules resolved from the body, weapon,
  abilities, conditions, and costs in [combat](../domains/tabletop/combat/__init__.py).
- [ ] C2 — Resolve learned spells, power, mana, range, targets, and eligibility from versioned definitions
  in [magic](../domains/tabletop/magic/__init__.py); remove player authority to choose arbitrary power/cost.
- [ ] C3 — Define action duration, movement budget, initiative/concurrent conflicts, resource consumption,
  condition/blessing expiry, incapacity, defeat, death, healing, rest, and recovery on the shared clock.
- [ ] C4 — Allocate seeds by distinct logical action from a recorded run seed/sequence. Retries reuse
  the original seed/receipt; two successive identical attacks must not reuse rolls merely because text matches.
- [ ] C5 — Reconcile portal sheet HP/status/equipment with kernel state; define one canonical owner for
  each value and projections for other views. Avoid stale character cards overwriting live outcomes.
- [ ] C6 — Make quest progress/rewards derive from authorized evidence and objective definitions;
  current quest requests supply their own amount and target. Extend economy/inventory/trade as needed for activities.
- [ ] C7 — Acceptance: human and autonomous actors use identical rule enforcement; invalid or impossible
  actions leave no writes; retries spend resources once; distinct seeded actions replay correctly.

## D. Persistent world clock and scheduler

- [ ] D1 — Define branch-scoped simulated time, units, speed, pause/resume, and advance-to boundaries.
  Wall-clock UTC remains operational metadata; unattended elapsed time is an explicit campaign policy.
- [ ] D2 — Register typed clock/scheduling commands through [tabletop registry](../domains/tabletop/registry.py)
  and the kernel. Preserve stable ordering and separate worlds/branches.
- [ ] D3 — Add a durable due-work repository with idempotent enqueue, claim/lease, retry, cancellation,
  and ordering. Use `DeterministicScheduler` as reference semantics, not as durable storage.
- [ ] D4 — Add a world-runner CLI/service in [main.py](../main.py) and [Compose](../infra/docker-compose.yml).
  Atomically connect execution receipts, completion, next work, and clock progress; recover after crashes.
- [ ] D5 — Enforce one authoritative execution owner per world/timeline; reject stale worker epochs.
  Refresh authoritative state between processes rather than relying on hydrated application caches.
- [ ] D6 — Coordinate observation projection before a dependent decision. Track event/subjective cursors;
  prevent agents deciding on missing observations or retries applying the same causal update twice.
- [ ] D7 — Acceptance: same seeds/order produce the same results, no viewers are required, two workers
  do not duplicate actions, pause stops progress, restart resumes, and catch-up honors configured time policy.

## E. Offscreen people and continuous activities

- [ ] E1 — Add typed activity definitions/state for work, travel, sleep, consumption, and interruptions
  under `domains/tabletop/activities/` (proposed). Persist start/due time, progress, inputs/outputs, owner, and cause.
- [ ] E2 — Connect materialized population state to due activities and canonical entities where needed;
  statistical/materialized/active representation must not create duplicate people or resource balances.
- [ ] E3 — Advance coarse offscreen activities from elapsed simulated time; use detailed actions when
  relevant. Choose update resolution from interaction needs, not whether a human camera observes the person.
- [ ] E4 — Reconcile pending work and progress on activation/deactivation in `PopulationLifecycle`;
  neither reset activity nor award its output twice. Define how relevance is computed automatically.
- [ ] E5 — Add persistent needs/routines and causal interruptions: hunger, fatigue, rain, danger,
  resource shortage, social obligations, travel arrival. Scope initial activity vocabulary explicitly.
- [ ] E6 — Acceptance: gardener weeds while party leaves; rain interrupts at the right time; returning
  party sees the resulting partial work and location. Repeat across deactivation and process restart.

## F. Autonomous decisions, models, and narration

- [ ] F1 — Connect due character work to context builder → candidate actions → layered cognition →
  typed proposal → normal command submission → observations → next work. Replan on invalidated actions.
  The bounded local movement loop is wired through these boundaries. Invalid actions pause visibly;
  richer replanning, goals, and activity scheduling remain open.
- [ ] F2 — Persist goals, plan progress, needs, cooldowns, and next-decision time. Execute plans stepwise;
  recheck preconditions rather than blindly applying an entire generated plan.
- [ ] F3 — Implement injected model providers behind [DeliberationProvider](../cognition/deliberation.py).
  Wire the API and worker composition; the current API passes no provider even for model runtime assignments.
- [ ] F4 — Add timeout/retry, usage accounting, context limits, provider configuration, recorded
  model/prompt versions, and deterministic fallback. Keep credentials server-side and out of traces.
- [ ] F5 — Add character dialogue generation and response scheduling. Actual speech still enters
  `tabletop.dialogue.speak`, with language/volume/perception and normal causal provenance.
- [ ] F6 — Add narration derived from committed facts with separate operator, spectator, and character
  scopes. Persist source event references; generated prose must not create uncommitted world facts.
- [ ] F7 — Detect repeated actions, conversation loops, and lack of progress; apply bounded recovery
  policies, preserve motive consistency, and expose failures to the operator.
- [ ] F8 — Acceptance: small cast pursues goals, converses, responds to interruptions, and reaches a
  consequential stopping condition without manual API calls; provider outage does not corrupt or endlessly spin the run.

## G. Player-history stand-ins and control handoffs

- [ ] G1 — Record decision authorship independently from actor authority: human input, stand-in,
  NPC policy/model, director, and operator. Link human decisions to player, character, context, options,
  dialogue, and outcome without revealing options/facts the character did not know.
- [ ] G2 — Add versioned behavior profiles keyed by player/character. Retrieve comparable human
  decisions to infer speech, priorities, relationships, risk, and tactical choices with confidence/provenance.
- [ ] G3 — Combine that history with character card/backstory: human evidence guides demonstrated
  behavior; card/backstory supplies initial identity and unknown situations. Surface contradictions for operator/player correction.
- [ ] G4 — Exclude autonomous decisions from human preference evidence. Define treatment of revised
  timelines and retain human-vs-stand-in provenance across restart and profile rebuilding.
- [x] G5 — Extend runtime assignment with exclusive control ownership, version/epoch, and an atomic
  handoff boundary. Reject stale in-flight proposals from a previous controller.
  Implemented for canonical LIVE runs: private controller state extends HUMAN/UTILITY runtime
  selection with owner/executor, epoch, mode, bounded steps, and due time. Reference state locks
  and durable branch locks serialize handoff with command fencing/commit. Managed requests carry
  the observed epoch; the server never stamps stale requests with new authority. Complete
  timeline/checkpoint integration remains I.
- [ ] G6 — Add explicit leave/takeover plus presence timeout/reconnect handling. Disconnect policy
  and campaign pause policy must be visible; identity stays the same while runtime changes.
  Explicit Let character act / Pause autonomy / Take control and persistent disconnect behavior
  are implemented. Automatic presence timeout/reconnect policy remains unimplemented.
- [ ] G7 — Authorize stand-in execution through explicit world/entity grants; do not impersonate a
  browser account or reuse its session. Record both execution authority and behavior-profile attribution.
  Dedicated AGENT execution, scoped grants, CHARACTER_POLICY ledger authorship, and pinned
  character/persona trace attribution are implemented. Learned player-behavior profiles remain G2/G3.
- [ ] G8 — Build an authorized recap from the character's actual experience; wire takeover/return
  controls through typed adapters and preserve partially completed actions exactly once.
- [ ] G9 — Acceptance: history-rich stand-in follows contextual human examples; history-free stand-in
  uses card/backstory; solo/mixed/all-autonomous modes work; takeover races commit one action; no character perceives handoff.

## H. In-world parties and transferable opportunities

- [ ] H1 — Add party membership independent of human account/game rosters and ownership.
  Model invitations, willingness, shared goals, departure, reunion, and hostility with causal events.
- [ ] H2 — Allow any eligible in-world entity to join based on circumstances and motives; support NPC
  companions without manufacturing a human account for each. Joining does not grant private knowledge or human body control.
- [ ] H3 — Define group movement, shared plans, leadership decisions, resources, and distributed knowledge.
  Group membership alone must not share every member's beliefs/secrets.
- [ ] H4 — Make quests/opportunities transferable where the fiction allows. Replace arbitrary
  protagonist/class gates with actual prerequisites; support alternate informants and approaches.
- [ ] H5 — Acceptance: an ordinary resident joins, contributes, can become human-controlled when
  authorized, leaves for a personal reason, and can carry an opportunity after another quest giver dies.

## I. Complete checkpoints, timeline revision, and correction

- [ ] I1 — Specify a consistent checkpoint manifest spanning canonical projection and entity metadata,
  secrets, minds/evidence/memories/relationships, population, control assignments, activities, clock,
  RNG allocation, story state, tasks, narrative/retrieval indexes, and relevant versioned artifacts.
- [ ] I2 — Add a pause/quiescence barrier for workers and projector. Checkpoint one causal boundary;
  identify pending outbox work and prevent a mix of pre-event bodies and post-event minds.
- [ ] I3 — Extend snapshot storage/repositories and hydrate all checkpoint components. Add scheduled
  and event-boundary checkpoints with operator labels and retention rules.
- [ ] I4 — Introduce campaign timeline lineage and an explicit active continuation pointer. Current
  `BranchKind` is canonical/trial; design revised canonical continuation without abusing evaluation
  branches or weakening their isolation. Preserve append-only abandoned history for operator audit.
- [ ] I5 — Add typed operator revise/correct/resume commands. Scope corrections to selected facts,
  validate the complete resulting state, and fence all old tasks, leases, requests, and queued outputs.
- [ ] I6 — Restore/rebuild subjective state and retrieval at the chosen boundary. Do not copy current
  minds into an earlier body snapshot or expose abandoned narration as character memory.
- [ ] I7 — Distinguish deterministic replay of committed deltas from fresh execution after a patch.
  Record correction reason, seed policy, source checkpoint, model versions, and resulting timeline.
- [ ] I8 — Support both rewind-before-death and explicitly chosen in-world resurrection. Rewind
  removes subsequent death-dependent consequences; resurrection retains what witnesses really experienced.
- [ ] I9 — Acceptance: revise a raid death, resume with coherent possessions/relationships/quests;
  discarded funeral memories never appear; restart mid-revision and recover without two active histories.

## J. World setup, factions, gods, and story direction

- [ ] J1 — Add versioned campaign/world definitions and validated setup commands for locations,
  initial population, factions, gods, resources, relationships, conflicts, and character placement.
  Reuse entity spawning; existing reputation/blessing commands are only individual effects.
- [ ] J2 — Add faction membership, leadership, territory, goals, resources, intelligence, and scheduled
  plans. Factions act through authorized agents with costs and limited knowledge.
- [ ] J3 — Define gods' domains, motives, followers, knowledge, intervention conditions/costs, and
  cooldowns. Apply effects through divine commands and expire durations on the world clock.
- [ ] J4 — Add story/set-piece definitions under `domains/tabletop/campaign/` (proposed): triggers,
  opportunity/required-event/fixed-scene strength, prerequisites, deadline, participants, and completion/failure evidence.
- [ ] J5 — Add director state for pacing, threat development, revealed clues, and alternative paths.
  Schedule opportunities within world rules; never turn a required event into an undeclared mandatory character choice.
- [ ] J6 — Reconcile missed set pieces, departed party members, dead informants, and divergent goals.
  Preserve consequences and expose conflicting authored requirements to the operator.
- [ ] J7 — Acceptance: the same setup supports materially different routes/endings; ignored factions
  still act; a required raid occurs without forcing characters to attend or choose a particular response.

## K. Temporary protection and intervention policy

- [ ] K1 — Add operator-only protection constraints with subject, scope, reason, milestone/expiry,
  and conflict behavior: allowed alternative outcome or pause. Avoid permanent accidental immortality.
- [ ] K2 — Evaluate constraints before outcome commitment through deterministic policy integrated
  with relevant actions. The model cannot silently ignore lethal damage or edit HP after publication.
- [ ] K3 — Keep protection metadata and intervention explanations outside character sensory events;
  characters perceive only the actual in-world result.
- [ ] K4 — Acceptance: needed quest giver survives a protected interval through an allowed result,
  can die after expiry, and revision works if protection is added after the original death.

## L. Executable AI DM/operator

- [ ] L1 — Inventory human DM/operator actions and expose equivalent typed tools: inspect/setup,
  spawn/place, manage factions/gods/parties, direct story, run/pause, checkpoint/revise, protect,
  inspect causes, and verify results. Include human-accessible tools for each supported operation.
- [ ] L2 — Add a world-scoped DM agent principal with explicit capabilities. Ordinary DM currently
  lacks `canonical.promote`; revision/operator powers need their own explicit grant and policy.
  Never give a model database credentials or arbitrary delta/SQL tools as a substitute.
- [ ] L3 — Add durable instruction → task → steps → tool receipts → verification state under
  `campaign/operator/` (proposed). Support progress, dependencies, cancellation, retry, and restart.
- [ ] L4 — Wire natural-language instruction handling to injected providers and the tool registry.
  Execute routine authorized work without per-step approval; ask only for material ambiguity or authority beyond the grant.
- [ ] L5 — Add supported task delegation/work queues with bounded scope, persistent ownership,
  and idempotent completion. This is product functionality, not permission for coding agents to spawn agents.
- [ ] L6 — Verify postconditions by reading authoritative state, not by trusting generated prose.
  Report completed/failed/blocked steps with receipts and concise causes; recover partial tasks.
- [ ] L7 — Keep DM knowledge, character contexts, and task/intervention records separate. In-world
  speech and lore are data, not authority to issue operator instructions.
- [ ] L8 — Acceptance: “create three rival factions,” “run until the capital,” and “return before the
  raid, keep the giver alive, continue” execute as durable verified tasks and recover after interruption.

## M. Operator and player experience

- [ ] M1 — Add campaign setup/editing, run/pause/speed/until controls, current activity, and a spectator
  story view. Show world time and whether the world continues when all humans leave.
- [ ] M2 — Add DM instruction console, task status, intervention history, and explanations of why an
  actor acted. Maintain authorized operator vs character viewpoints on the server as well as in navigation.
- [ ] M3 — Add checkpoint/timeline browser, correction preview, protection editor, and resume controls.
  Identify active history clearly and invalidate stale client caches when history changes.
- [ ] M4 — Expose backstory, history-based stand-in status, takeover/leave, and return recap.
  Explain uncertain behavioral inference without exposing another character's hidden information.
- [ ] M5 — Meet keyboard/focus/mobile/loading/error/empty-state requirements. Use feature `api.ts`
  adapters; rebuild current `static/v2` production assets after source changes.

## N. Persistence, operations, documentation, and gates

- [ ] N1 — Add sequential migrations after the current highest migration; never edit applied SQL.
  Include composite lineage keys, least privilege, actor-local context, appropriate forced RLS,
  immutable evidence, and integration tests for new constraints/policies/grants/restart paths.
- [ ] N2 — Extend readiness/status with runner heartbeat, timeline owner, stuck work, projector lag,
  task failures, and model availability. Distinguish an HTTP-ready service from a progressing campaign.
- [ ] N3 — Set concurrency, population/activity batching, storage retention, model budgets, and run
  limits. Measure busy-world throughput and inspect long-running behavior rather than claiming scale from schema alone.
- [ ] N4 — Extend consistent backup/restore for all campaign components and test an isolated restore.
  Keep secrets, private notes, model credentials, and character hidden state out of public diagnostics.
- [ ] N5 — Investigate the reported GitHub integration setup failure against its exact commit/logs.
  This review inspected workflow source, not the remote run. CI currently starts dependencies without
  an explicit readiness step; establish the actual cause before selecting a fix.
- [ ] N6 — Align CI mypy targets with repository guidance (currently omits `identity` and `infra`).
  Run fast/type gates, isolated integration tests, browser journeys, and wheel/image checks as applicable.
- [ ] N7 — Document new behavior/routes/roles/stores/configuration/commands/test lanes in README,
  architecture/kernel/API/operations/network/testing docs and changelog alongside implementation.
  Update wheel verification and package inclusion for new migrations/runtime assets.
- [ ] N8 — If remote play is desired, configure authenticated encrypted access deliberately;
  current loopback binding does not provide remote access. 3D rendering remains a separate optional scope.

## Acceptance milestones

- [ ] MILESTONE 1 — Two clients complete a basic session with bound bodies, correct rules, fresh
  scenes, and private knowledge preserved; durable restart works.
- [ ] MILESTONE 2 — Unattended village: gardener, traveler, merchant, and faction advance on one
  clock with no connected humans; interruptions and restart produce coherent state.
- [ ] MILESTONE 3 — Small autonomous adventure: cast follows motives, talks, changes plans, and
  reaches a meaningful ending; set pieces allow divergence and operator knowledge stays private.
- [ ] MILESTONE 4 — Human joins/leaves/rejoins while companions continue; stand-in follows human
  history or card/backstory fallback; ordinary resident can join and leave the party.
- [ ] MILESTONE 5 — Operator revises a consequential death, patches history, and resumes; all
  dependent state agrees and characters have no discarded memories or simulation awareness.
- [ ] MILESTONE 6 — AI DM completes the same setup/run/revision tasks through natural-language
  instructions, verifies results, and survives interruption without duplicate changes.

## Verification evidence for this document

The initial checklist pass was static code inspection and documentation/link validation. Earlier session evidence:
durable startup/readiness succeeded; 14 existing focused lifecycle/kernel/subjective/trial tests
passed before this documentation change. Those tests do not establish the milestones above.
For A1 implementation, the full fast gate passed (156 Python tests, 20 frontend tests, lint and
production build); mypy passed; all 34 integration tests passed against an isolated database.
Final current-world DM lookup enforcement was additionally checked with service tests and the
isolated Chromium journey. A complete campaign/model-backed playthrough remains untested.
The running Docker app was not redeployed; local source and current production assets changed.

For B1, the current fast gate passed (165 Python tests, 20 frontend tests, lint and production
build); mypy passed for 99 source files; all 36 integration tests passed, including upgrade from
migration 003, purpose constraints/rollback, and actual API-process restart. Authenticated Chromium
verified persona creation/successors/compile/prompts and the existing Persona Studio at desktop
and mobile sizes against an isolated ready reference server. A wheel built from a clean staging
tree passed the runtime-asset verifier. Frontend assets are unchanged. The live Docker database
and image were not upgraded; independent Orderly acceptance remains separate.

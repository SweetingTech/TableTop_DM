# Autonomous campaign implementation checklist

The original review started at commit `9d5a26a` on November 10, 2026. This checklist tracks
implementation and verification for the full campaign scope. The README describes the shipped
features and links to the operator guides.

Implementation tracking: [Orderly campaign board](http://jarvis:8080/b/tabletop-dm-autonomous-campaign).
Checked items mean locally implemented and verified; Orderly acceptance and live deployment are separate.
Orderly has completed Tasks 1–5. Task 6 tracks offscreen activities. The board shows
live acceptance and the open items that follow it.

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
| Character binding | [Roster finalization](../kernel/api/roster.py) prepares a retryable uncontrolled body/binding, then publishes the seat and typed control changes atomically | In-world party membership independent of the roster remains H1 |
| Console | [Page](../frontend/src/features/game-console/GameConsolePage.tsx) polls authorized versioned scenes, ignores stale responses, and renders all positioned perceived tokens using zone map configuration | Campaign supervision and intervention experience remain section M |
| Commands | [Bus](../kernel/command_bus.py), [application](../kernel/application.py), [durable repository](../kernel/postgres_repository.py) | No connected autonomous campaign driver |
| Scheduling | [World runner](../kernel/world_runner.py) and [clock commands](../domains/tabletop/world_time.py) advance one branch clock through leased PostgreSQL work | Persistent character plans and their own next-decision work remain F2 |
| Population | [Lifecycle](../population/lifecycle.py), [routines](../population/routines.py), and [life plans](../population/life.py) share the clock and each bound body's physical resources | The activity vocabulary is bounded to work, rest, meals, local travel, sleep, and social obligations |
| Background process | [World event projector](../cognition/projector.py), [character runner](../cognition/runner.py), and [world runner](../kernel/world_runner.py) run independently of a viewer | A complete cast-and-story stopping condition remains F8 |
| Decisions | [Character context and proposals](API_AND_WORKFLOWS.md#trusted-character-proposals) supply trusted perception and a typed candidate set | The broader deliberation provider, bounded replanning, and scoped narration remain section F |
| Personas | Purpose-separated [compiler](../persona/compilation/compiler.py), pinned character cards, and scoped human choice evidence | Broader longitudinal player-history behavior remains section G |
| Runtime assignment | [Controller handoff](API_AND_WORKFLOWS.md#controller-handoff-and-runner) fences exclusive human/runner ownership by epoch | Configurable unattended and multiplayer policies remain section G |
| Experiments | [ApplicationBranchExecutor.execute](../experiments/executor.py) | Applies a single scenario intervention, returns `steps=1`; horizon metadata is not a live campaign loop |
| Factions/gods/quests | [Reputation](../domains/tabletop/factions/__init__.py), [blessing](../domains/tabletop/divine/__init__.py), [funded quest contracts](../domains/tabletop/quests/__init__.py) | Quest evidence is kernel-derived; autonomous faction/divine agendas and pursuit of quest opportunities still require later checklist work |
| History | [Snapshots](../kernel/snapshots.py), [replay](../kernel/replay.py), [branching](../kernel/branching.py) | Snapshots contain projections; replay applies committed deltas; neither provides complete campaign revision |
| Lore | [Character knowledge](API_AND_WORKFLOWS.md#character-knowledge) retrieves from learned testimony and pinned starting claims | Authored campaign direction and story set pieces remain section J |

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
- [x] A2 — Make roster update, entity creation, character binding, and authority changes recoverable
  as one logical operation. Cover missing
  live run, missing character, wrong owner/world, retry, reassignment, and partial failure.
  Preparation grants no control; failed preparation retains an uncontrolled deterministic body and
  pinned binding for retry. Final publication joins the seat, grants, projection, ledger and outbox
  in one durable transaction. Injected binding/publication/event failures and restarted retries are tested.
- [x] A3 — Define whether removing a member removes control, keeps an autonomous character,
  or only removes the human seat. Wire through [portal](../domains/tabletop/portal.py) and
  [identity grants](../identity/repository.py); never leave stale body control accidentally.
  Removing the last seat retains the body/card/mind/history and world role, revokes human control,
  pauses its runner and advances its epoch. Another game's seat preserves the grant. Rejoining restores
  control without replacing identity. Reference/RLS checks fence explicitly removed seats while preserving
  legitimate DM runtime ownership of unowned NPCs; stale executor and raw owner SQL are rejected.
- [x] A4 — Refresh the scene after accepted actions, wait for the relevant observation projection
  boundary, and deduplicate pending versus persisted feed entries. Clear local state on world/viewpoint changes.
  Implemented with an authorized receipt cursor, bounded/cancellable polling, request-local durable
  observation reads, and an observation-only feed. Verified with delayed-projection/retry/scope
  regressions and a real built-SPA cookie session at desktop/mobile sizes. Failed reads retry GET
  without resubmitting accepted actions. Durable readiness also recognizes complete immutable observations
  at stored confidence precision without rewriting their IDs, masks or frozen audiences.
- [x] A5 — Add version/cursor-based updates across clients, reconnect/resync, and out-of-order response
  protection. Start with bounded polling if appropriate; preserve perception-scoped reads.
  Visible tabs poll serially every 2.5 seconds, resynchronize on reconnect/focus and reject obsolete or older
  replies. Same-version newly projected observations still update. Draft/focus survive background reads;
  denied access clears the scene. Existing-world viewpoints reflect reassignment through another API process.
- [x] A6 — Replace fixed map metadata with world/zone presentation configuration; remove the four-token
  limit. Check [map positioning](../frontend/src/features/game-console/mapPosition.ts) against zone coordinates.
  Typed map configuration exposes only perceived-zone presentation to the human interface. Every positioned
  perceived token is rendered; inclusive cell centers support negative/translated extents. Unknown positions
  are never invented, and out-of-range known coordinates use an explicitly labeled fitted grid.
- [x] A7 — Handle missing run/body, inspect-only viewpoints, unsupported commands, and stale versions
  with actionable UI states. Never present failed writes as successful demo actions.
  Live errors never become demo success. Stale or projection-pending scenes disable acting with recovery
  guidance; missing runs/bodies and inspect-only viewpoints explain the required next action.
  Unknown slash commands list the supported actions and retain the draft without posting an
  uninterpreted proposal as a successful action. Parser/API tests and the actual A8 browser journey cover it.
- [x] A8 — Acceptance: invite and bind a character, speak/move/attack, observe correct health/position
  from two authorized clients, switch viewpoints without mixed observations, and restart successfully.
  The built-SPA journey uses isolated PostgreSQL, a real projector, two independent player cookie contexts
  and DM UI invitations. It verifies six map tokens/coordinates, cross-client movement/HP/single speech,
  draft/feed isolation, offline recovery, app restart and mobile speech after restart (47.81 seconds).
  Final local gates: 596 Python unit/contracts, 63 frontend tests, lint/build, 143 typed modules, clean wheel and
  90 documentation links. Full durable run: 136 passed before the final owner-fence correction; all 6 affected
  roster/migration tests then passed on corrected source. Orderly subsequently completed Task 2.

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
- [x] B3 — Introduce a trusted character-context builder under `cognition/`. Resolve current scene,
  mind, remembered testimony, known lore, and legal action candidates for one world/branch/entity.
  Reuse [scene](../domains/tabletop/spatial/scene.py), perception contracts, and mind repositories.
  The shared scene service and read-only [context builder](../cognition/context.py) validate frozen
  same-branch evidence, memories, beliefs and learned lore. Context, retrieval and proposals share
  a projection barrier. The current movement/speech/fixed tactical catalog uses world/body authority
  and perceived self state; hidden obstacles never filter attempts. Richer activity/planning
  catalogs extend this seam under later action/runner work. Kernel submission still decides outcomes.
- [x] B4 — Wire `cognition_decide` and the autonomous runner to that builder. Keep externally supplied
  evaluation situations confined to explicit privileged/testing flows rather than trusting them for live minds.
  Explicit CHARACTER mode on `cognition_decide` now shares the trusted scoped proposal builder
  and receipts; it accepts only world/branch/run/entity/key and rejects caller context/actions/seeds.
  The legacy caller-authored endpoint remains privileged playtester evaluation only and rejects CHARACTER
    personas. A trusted CHARACTER proposal endpoint now resolves pinned identity/context/actions,
    derives scoped server seeds, waits for sensory projection, and stores private append-only
    idempotent receipts plus traces atomically (006). It uses local basic movement utility policy,
    returns PROPOSAL_ONLY. A separate bounded runner now consumes that builder and submits fenced
    kernel commands after explicit controller handoff (007), with atomic step/budget accounting,
    observation readiness, concurrent retry/restart recovery, and player takeover. Caller-authored
    evaluation remains privileged playtester-only. The runner now uses history/persona-guided
    movement, speech and fixed tactical choices. Longer planning and story goals remain F/G/D.
- [x] B5 — Route lore retrieval, summaries, and model conversations through the same knowledge and
  timeline boundary. Public availability must not automatically mean a character has learned a fact.
  Added [character knowledge](API_AND_WORKFLOWS.md#character-knowledge) from validated physical
  testimony and pinned starting claims, including older facts beyond recent conversation. Retrieval
  never fills gaps from public/global lore; dialogue shares the same source view and private provenance.
- [x] B6 — Label operator/director records outside the sensory event stream. Audit [event finalization](../kernel/event_factory.py),
  observations, prompts, receipts, and retrieval so revision notes/protection rules never become character evidence.
  Kernel finalization suppresses non-sensory physical builders/resolvers. Context, memories,
  retrieval and dialogue preserve that boundary; broad scene inspection grants no private mind access.
- [x] B7 — Acceptance: seed hidden plot facts and abandoned-timeline facts; verify they cannot enter
  character context, speech, memory, or retrieval. Test god knowledge limits and human-player/character separation.
  Causal relationship hardening derives controlled reactions from frozen physical evidence and
  rejects arbitrary promise/rescue labels. Current branch-lineage knowledge acceptance is verified;
  complete revised-canonical continuation and discarded-state restoration remain section I.
  Knowledge regressions cover hidden masks/operator sources, deity versus operator knowledge,
  pinned card edits, other worlds, trial-only testimony after restart and provider inputs without
  source/controller metadata. Final Python439/type136/frontend44/browser4/wheel/link gates passed.
  The broad durable run passed117/118; its immediate-context assumption was updated to assert409,
  real projection, then200, and all13focusedcontroller/knowledge/dialoguecases passed afterward.
  Current-head GitHub CI and independent Orderly acceptance remain separate pending requirements.
  Native review subsequently accepted all original B1–B7 criteria (verdict4c0e329e,
  events2129367/2129368); task3 is independently COMPLETED. Runtime90 and actual verification91
  are merged. The reports pin their tested revisions; full campaign milestones remain unaccepted.

## C. Make action outcomes authoritative

- [x] C1 — Replace caller-selected attack bonuses/dice with rules resolved from the body, weapon,
  abilities, conditions, and costs in [combat](../domains/tabletop/combat/__init__.py).
  Target-only attacks now use registered owned weapons, canonical STR/finesse DEX and training,
  reach, sight, zone, incapacity and poison/fear disadvantage. Typed bounded body definitions
  configure legacy scoreless bodies without card guesses; ordinary owned-weapon equip shares
  action/initiative costs and retry enforcement. Live sheets show canonical scores/bonuses.
  PR103 is merged after current-head gates. Exact source and actual results are retained in
  [section C verification](verification/section-c/README.md); independent Task4 acceptance remains separate.
- [x] C2 — Resolve learned spells, power, mana, range, targets, and eligibility from versioned definitions
  in [magic](../domains/tabletop/magic/__init__.py); remove player authority to choose arbitrary power/cost.
  Both cast/invoke use registered ARCANE_BOLT/MEND rules and body-owned known spells/mana;
  initial card validation precedes roster writes, and later card edits cannot refill/teach bodies.
  Broader spells/loadouts remain future content. This implementation's CI, merge and independent
  task acceptance are separate gates; section C and campaign milestones remain incomplete.
- [x] C3 — Define action duration, movement budget, initiative/concurrent conflicts, resource consumption,
  condition/blessing expiry, incapacity, defeat, death, healing, rest, and recovery on the shared clock.
  Shared voluntary-action incapacity and transactional human wakeup are wired, sleeping
  stand-ins suspend, and ordinary healing cannot resurrect dead-marked bodies. Own scene status
  prevents impossible stand-in choices without revealing others' private conditions. Configured
  clocks now reserve body readiness atomically: six-second physical actions and speed-owned
  grid-step costs; guards expire through clock advance. Speech remains free. Retries preserve costs;
  competing commands serialize; waiting/racing stand-ins preserve controller budgets. Clockless
  legacy branches remain untimed. Typed bounded conditions and independent blessing expiries now
  share chronological clock/weather/readiness boundaries. Permanent sources survive temporary
  expiry; blocked offscreen work and attendance do not accrue, and missing-health guards remain.
  New damage-induced defeats now use seeded six-second death saves and clocked stabilization/recovery;
  living 0-HP bodies can receive MEND or adjacent first aid. Dead/unconscious bodies receive no new
  sensory grants. Shared-clock rest now has fixed hourly/eight-hour recovery, canonical HP/mana
  capacities, interruptions and the same offscreen NPC sleep/rest rules. Versioned seeded initiative
  now selects six-second participant windows over that same clock; ordinary costs, concurrent
  retries and offscreen readiness share enforcement. Missed windows do not freeze the world.
  These mechanics are merged through PR99–102 and pass actual unit, durable and browser gates.
  See [retained verification](verification/section-c/README.md). Independent all-C acceptance
  still precedes leaving section C.
- [x] C4 — Allocate seeds by distinct logical action from a recorded run seed/sequence. Retries reuse
  the original seed/receipt; two successive identical attacks must not reuse rolls merely because text matches.
  Both commit adapters derive physical seeds under the branch lock
  from run seed and next branch sequence, separate from policy seeds. Private typed proofs support
  replay; legacy null run seeds use zero. Reference concurrency, durable parity/restart/retry,
  actual concurrent transactions, privileged replay and pre-proof receipt upgrade regressions pass.
  Current-head CI, independent review/integration and whole-section C acceptance remain separate.
- [x] C5 — Reconcile portal sheet HP/status/equipment with kernel state; define one canonical owner for
  each value and projections for other views. Avoid stale character cards overwriting live outcomes.
  Backend read foundation: owner/world/body-authorized live-state endpoint projects only the
  canonical body's current physical resources with branch/version and no-store responses. Reads
  never sync values into authored cards or fall back for missing bodies. Bound-card editing now
  rejects HP/status/maxHP/armor/speed and world retargeting, with owner/admin parity and atomic
  mixed-request rejection. The Dashboard consumes live resources read-only, with serial visible-tab
  polling, cancellation, manual refresh and loading/error states without stale card fallback.
  Identity drafts survive polling; unbound cards retain starting-resource controls. Unit, durable
  and real-browser verification cover this ownership boundary. Whole-section C acceptance remains open.
- [x] C6 — Make quest progress/rewards derive from authorized evidence and objective definitions;
  replace legacy requests supplying their own amount and target. Extend economy/inventory/trade as needed for activities.
  Trade now has maker-authorized carried escrow, fixed-price reference-only acceptance, physical
  contact/visibility/capacity, both-body costs, clock expiry/refund and perceived console offers.
  Human/agent parity, actual durable restart/rollback/replay/race and built desktop/mobile paths
  cover that portion. Quest contracts now define bounded MOVE/DEFEAT/TRADE/WEED objectives and
  funded item/gold rewards. Authorized physical/clock results derive progress atomically;
  distinct defeat targets count once, historical work is excluded and clients cannot supply
  progress, targets or payout terms. Controlled physical acceptance and READY reward claims,
  public receipt redaction with world-scoped privileged inspection,
  manager cancellation/refund, private evidence provenance and perceived offers/personal journal
  have unit, durable and browser coverage. PRs 104–107 are merged. PR 106 closes
  separate-process grant revocation for private receipt inspection. Autonomous pursuit remains
  section F. See [exact revisions and evidence](verification/section-c/README.md).
- [x] C7 — Acceptance: human and autonomous actors use identical rule enforcement; invalid or impossible
  actions leave no writes; retries spend resources once; distinct seeded actions replay correctly.
  Actual human/agent trial and runner cases, concurrent-worker/restart/rollback/replay cases,
  private receipt revocation and live browser journeys pass. The full local durable core lane
  passed158 cases; exact code/revision differences and current focused checks are explicit in
  [the evidence packet](verification/section-c/README.md). Orderly independently accepted all
  seven original criteria and completed Task 4 in review session
  `42ae499e-a2b9-4a8d-9bf6-f76b2270089a`.

## D. Persistent world clock and scheduler

- [x] D1 — Define branch-scoped simulated time, units, speed, pause/resume, and advance-to boundaries.
  Wall-clock UTC remains operational metadata; unattended elapsed time is an explicit campaign policy.
- [x] D2 — Register typed clock/scheduling commands through [tabletop registry](../domains/tabletop/registry.py)
  and the kernel. Preserve stable ordering and separate worlds/branches.
- [x] D3 — Add a durable due-work repository with idempotent enqueue, claim/lease, retry, cancellation,
  and ordering. Use `DeterministicScheduler` as reference semantics, not as durable storage.
- [x] D4 — Add a world-runner CLI/service in [main.py](../main.py) and [Compose](../infra/docker-compose.yml).
  Atomically connect execution receipts, completion, next work, and clock progress; recover after crashes.
- [x] D5 — Enforce one authoritative execution owner per world/timeline; reject stale worker epochs.
  Refresh authoritative state between processes rather than relying on hydrated application caches.
- [x] D6 — Coordinate observation projection before a dependent decision. Track event/subjective cursors;
  prevent agents deciding on missing observations or retries applying the same causal update twice.
- [x] D7 — Acceptance: same seeds/order produce the same results, no viewers are required, two workers
  do not duplicate actions, pause stops progress, restart resumes, and catch-up honors configured time policy.

Migration 014 adds one pending due clock step per durable canonical branch, with a scoped lease,
retry backoff and cancellation. The tick and its successor commit in the existing kernel
transaction. API and worker projectors now share the branch's first unpublished outbox row as
their ordering boundary. The character proposal path waits for the body's exact frozen grants to
project. Focused clock tests verify deterministic catch-up and exact pause boundaries. The
[PostgreSQL world-runner tests](../tests/integration/test_world_time.py) verify progression
without viewers, restart recovery, and two workers advancing one timeline without duplicates.
PR 108 merged the complete scheduler work. Orderly accepted all seven criteria and completed
Task 5 in review session `a41d2017-ceef-42b8-b545-a6274247f57c`.

## E. Offscreen people and continuous activities

Initial D/E foundation now persists branch time and WEED/REST activities through typed canonical
commands, with a separate world-runner, explicit downtime policy, epoch/step fencing, deterministic
weather boundaries and inspected scene/console progress. Tests cover no viewers, concurrent workers,
restart, rollback and character/world execution on one branch. Section D adds durable clock
leases.
See [world time and activities](API_AND_WORKFLOWS.md#world-time-and-offscreen-activities).

Population binding now connects materialized members to a single canonical body. Live lifecycle
metadata is branch-local; migration 011 freezes the source rather than keeping a second mutable
resource store. Opt-in WEED/REST/EAT routines persist hunger, fatigue, finite food consumption and
partial work across physical relevance, lifecycle transitions and worker restart. Physical anchors
drive automatic relevance independently of human presence. The same routine advances across both
levels, and a bound NPC's authorized controller adds detailed actions while physically relevant.
Opt-in life plans now add local home/work commutes, fixed daily sleep and
joint recurring social commitments, with arrival/deadline checks and causal waits/misses. Injuries
wake sleepers; asleep character policies retain their action budgets and humans can wake by acting.
Opt-in daily planning now selects prioritized local work/rest goals with daily quotas, responds to
rain/injury/food shortage, returns after displacement and retries blocked goals. Persistent choices
and goal fulfillment survive restart and split ticks. Optional motivation now ranks the bounded
work/rest menu using pinned CHARACTER traits and validated own beliefs. Heard importance/danger
claims can interrupt choices without changing truth or exposing private intentions. The explicit
NPC card association requires no player seat. Frozen inputs, effects and replay stay atomic.
An offscreen NPC retains its controller budget and current work. The kernel rechecks relevance at
commit so a prepared detailed action waits if the party leaves first.
The first independent review passed E2–E6 and reopened E1 for due-time and resource accounting.
The E1 repair persists those fields, records phases replaced within one clock command in its
immutable event, and preserves replay of older activity rows. A routine also records the cause
and time when it suspends work, and the reason for starting the replacement activity. The
[Orderly task](http://jarvis:8080/b/tabletop-dm-autonomous-campaign/t/6/w/1) shows acceptance.
Cross-zone routes, additional occupations and unrestricted goal generation are future scope.
See [life plans](API_AND_WORKFLOWS.md#travel-sleep-and-social-obligations).
See [subjective NPC goals](API_AND_WORKFLOWS.md#belief-and-persona-driven-npc-goals) for setup and limits.

- [x] E1 — Add typed activity definitions/state for work, travel, sleep, consumption, and interruptions
  under `domains/tabletop/activities/` (proposed). Persist start/due time, progress, inputs/outputs, owner, and cause.
- [x] E2 — Connect materialized population state to due activities and canonical entities where needed;
  statistical/materialized/active representation must not create duplicate people or resource balances.
- [x] E3 — Advance coarse offscreen activities from elapsed simulated time; use detailed actions when
  relevant. Choose update resolution from interaction needs, not whether a human camera observes the person.
- [x] E4 — Reconcile pending work and progress on activation/deactivation in `PopulationLifecycle`;
  neither reset activity nor award its output twice. Define how relevance is computed automatically.
- [x] E5 — Add persistent needs/routines and causal interruptions: hunger, fatigue, rain, danger,
  resource shortage, social obligations, travel arrival. Scope initial activity vocabulary explicitly.
- [x] E6 — Acceptance: gardener weeds while party leaves; rain interrupts at the right time; returning
  party sees the resulting partial work and location. Repeat across deactivation and process restart.

## F. Autonomous decisions, models, and narration

- [x] F1 — Connect due character work to context builder → candidate actions → layered cognition →
  typed proposal → normal command submission → observations → next work. Replan on invalidated actions.
  A failed physical action evaluated against a newer committed revision rebuilds the character's
  scoped context under a bounded retry budget. Reference and PostgreSQL tests cover a conflicting
  heal, a fresh decision, and rejection of the superseded attempt after worker restart.
- [x] F2 — Persist goals, plan progress, needs, cooldowns, and next-decision time. Execute plans stepwise;
  recheck preconditions rather than blindly applying an entire generated plan.
  Recovery plans record withdrawal, healing, needs, and cooldown in private receipts. Each
  decision rechecks the scene and continues only from the preceding accepted command. PostgreSQL
  verification restarts the worker between steps.
- [x] F3 — Implement injected model providers behind [DeliberationProvider](../cognition/deliberation.py).
  Wire the API and worker composition. The operator may opt in to an OpenAI-compatible model.
  Its action choices use the existing typed allowance and normal command authority.
- [x] F4 — Add timeout/retry, usage accounting, context limits, provider configuration, recorded
  model/prompt versions, and deterministic fallback. Keep credentials server-side and out of traces.
  Verify a bounded retry, stable fallback, recorded request usage and concurrent world progress
  through loopback and durable runner tests.
- [x] F5 — Add character dialogue generation and response scheduling. Actual speech still enters
  `tabletop.dialogue.speak`, with language/volume/perception and normal causal provenance.
  A due character can respond to scoped speech. The receipt records the observation and due time,
  and the committed command retains the source and conversation correlation across restart.
- [x] F6 — Add narration derived from committed facts with separate operator, spectator, and character
  scopes. Persist source event references; generated prose must not create uncommitted world facts.
  The narration API renders selected physical facts and preserves source event and viewpoint
  observation lineage across restart. Actors can retrieve their own entries with current authority.
- [x] F7 — Detect repeated actions, conversation loops, and lack of progress; apply bounded recovery
  policies, preserve motive consistency, and expose failures to the operator.
  Recovery filters zero-damage repeat attacks, repeated physical backtracking, and overlong
  grounded reply chains. The model sees eligible alternatives from the same plan. An exhausted
  plan records a private controller pause reason.
- [x] F8 — Acceptance: small cast pursues goals, converses, responds to interruptions, and reaches a
  consequential stopping condition without manual API calls; provider outage does not corrupt or endlessly spin the run.
  The [unattended cast test](verification/section-f/acceptance.md) launches real workers to heal,
  converse, and resume weather-interrupted work before an authored stopping boundary. It covers a
  working dialogue provider and HTTP 503 fallback, with stable results after restart.

## G. Player-history stand-ins and control handoffs

Current bounded extension: optional OpenAI-compatible speech expression (operator selects provider,
off by default) uses sourced subjective experience and preserves policy-selected intent/volume.
Fixed guard/bolt/mend tactics and new human choice evidence are wired through the real runner.
Generic phrasing imitation, ally/relationship strategy, full tactical plans, world goals and complete
rewind remain incomplete; these foundations do not close all F/G acceptance criteria.

- [ ] G1 — Record decision authorship independently from actor authority: human input, stand-in,
  NPC policy/model, director, and operator. Link human decisions to player, character, context, options,
  dialogue, and outcome without revealing options/facts the character did not know.
  Movement foundation: server-derived input origin is distinct from controller authority; private
  append-only samples link accepted manual choices to player, character, binding, pre-command
  perceived features, four attempted options and source outcome. All other decision types and
  richer authorship categories remain open.
- [ ] G2 — Add versioned behavior profiles keyed by player/character. Retrieve comparable human
  decisions to infer speech, priorities, relationships, risk, and tactical choices with confidence/provenance.
  Movement foundation: private content-addressed profiles use up to 256 accepted manual movement
  samples in the exact player/character/world/branch/run/body, matching perceived layout, distance,
  injury and company. Profiles freeze in proposal receipts with evidence IDs and confidence.
  Relationships, broader risk/tactics inference and negative-choice learning remain open.
  Speech/combat extension: new profiles now learn template intent/volume, basic melee target style,
  advance/withdrawal from matching new human choices. Open-ended phrasing, relationship strategy,
  spells and full tactical planning remain open.
- [ ] G3 — Combine that history with character card/backstory: human evidence guides demonstrated
  behavior; card/backstory supplies initial identity and unknown situations. Surface contradictions for operator/player correction.
  Comparable movement history now guides advice and the runner, with pinned persona curiosity/risk
  weights and an explicit limited English authored-tendency vocabulary as fallback. Private conflict
  notices are inspectable through behavior-profile GET. Broad semantic interpretation remains open.
  Compiled risk/conflict/social/directness and explicit peaceful/aggressive card tendencies now
  drive speech/combat fallback; choice-profile GET exposes separate versioned scores and conflicts.
- [ ] G4 — Exclude autonomous decisions from human preference evidence. Define treatment of revised
  timelines and retain human-vs-stand-in provenance across restart and profile rebuilding.
  Migration 008 atomically records only untraced accepted HUMAN_INPUT movement. Operator automation,
  submitted policy advice, autonomous actions, unknown legacy origin and foreign scope are excluded.
  Origins survive restart; no historical backfill guesses authorship. Complete rewind/restoration
  and broader decision types remain open.
  Migration 009 extends atomic source-linked evidence to contextual speech/combat/movement and
  preserves synthetic exclusion. Context uses canonical source order for equal timestamps; full
  rewind/restoration and arbitrary decision types remain open.
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
  Snapshot 2.1 freezes projection plus entity identity/controller/secrets for exact nested trials.
  Migration 012 preserves metadata-distinct artifacts. This remains a partial foundation: subjective
  state, population sources, controller assignments and narrative/retrieval stores are not restored.
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

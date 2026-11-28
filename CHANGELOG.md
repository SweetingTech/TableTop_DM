# Changelog

- Resume an activated timeline with a durable retry receipt. Reauthorize the archived
  controllers, restart the world clock on the new branch, and fence stale writes.
  Match controller handoff lock order and keep checkpoint outbox drain working across
  backward wall-clock adjustments.

- Activate a prepared rewind in one database transaction. Restore the paused branch
  and its retained witnesses, choices and population, then switch the active pointer.
  The registered activation command records a private event and queues its publication.

- Prepare branch-local copies of retained physical grants and subjective state.
  Rewind plans bind that reconstruction before activation.

- Prepare private, durable rewind plans from a verified checkpoint. Plans bind the
  active epoch, new run identity, seed policy and candidate state while play continues.

- Verify archived event, command, and perception prefixes and pinned file artifacts when
  reopening a campaign checkpoint or confirming the retained copies before cleanup.

- Record one active canonical continuation per world, with an epoch and durable lineage.
  World loading, run selection, and clock work follow that continuation.

- Add opt-in retention for scheduled campaign checkpoints. Preserve manual and pinned archives,
  verify the newest retained copies, and record retirement before cleaning up archive files.

- Schedule campaign checkpoints on the simulated clock or at matching committed events. The
  world runner finishes the held archive and resumes the branch after projection completes.
- Capture a private, integrity-checked campaign archive from a ready checkpoint hold. Migration 022
  binds the named receipt to its exact world, branch, request, projection and projected prefix.
- Hold a canonical branch at a fixed checkpoint boundary while its existing perceptions finish
  projecting. Migration 021 preserves the hold across API and worker restarts.
- Let funded quests designate alternate contacts and approaches, require specific items, and
  transfer responsibility with consent while preserving progress and single-payout escrow.
- Add party plans, consensual waypoint travel, leadership changes, and a physically located cache
  funded by members' own supplies.
- Let autonomous residents answer party invitations from the proposed motive and their own
  experiences. Restore pinned character traits for live decisions after a PostgreSQL restart.
- Record in-world party invites, consent, departures, hostile exits, and reunions through the
  controlled body. Residents can join a party without a player account.
- Score human preferences using choices the player actually had. Options never offered keep the
  character's fallback. Verify solo, mixed, and all-autonomous control in one durable campaign.
- Use PostgreSQL time for durable presence deadlines so clock skew does not reject renewals or
  end a player's turn early.
- Learn whether the player favors self-healing or helping a character who previously mended
  them. Migration 020 preserves earlier choice evidence and records comparable alternatives.
- Show a private recap of the character's witnessed experience between handoff and takeover.
  Migration 019 records exact committed revision bounds for new handoffs.
- Add opt-in disconnect timeout and explicit reconnect takeover in Character control. Migration
  018 protects the private presence deadline and preserves the existing controller epoch fence.
- Learn a private speech cadence from comparable committed human replies. Use it with a
  configured dialogue provider and deterministic fallback. Migration 017 preserves older evidence.
- Record private stand-in, NPC policy, and NPC model decision origins through the existing
  controller workflow. Migration 016 preserves previous classifications and human-history rules.
- Bound stalled character decisions using committed movement, ineffective strikes, and witnessed
  speech chains. Record attempted recovery privately and pause when the current plan has no option.
- Add operator, spectator, and character narration from committed events. Migration 015
  retains each line with its source and enforces actor-scoped access across restart.
- Rebuild a character's decision after a committed world change invalidates a queued action.
  Fence superseded attempts across workers and restarts, and pause when the retry budget is spent.
- Carry a critically wounded character's withdrawal and healing plan across worker restart.
  Recheck perceived threats and bodily needs before each action and record the private cooldown.
- Add optional OpenAI-compatible action selection for the API and runner. Bound provider input,
  deadline and retries, record reported usage, and use deterministic utility during outages.
- Schedule replies from the character's own perceived speech. Link each committed response to
  the utterance it answers and consume the cue after the response commits.

- Persist runnable activity due times and actual resource inputs and outputs. Clock events retain
  accounting for work, meals, rest, travel, sleep, and social phases replaced within one advance.
- Record why a routine switches activities and retain the interruption cause and time when
  the original work resumes.
- Refresh the GitHub README, add campaign artwork, and bring the campaign checklist and operator
  guides up to date.

- Let population-bound NPCs use their authorized detailed character actions during physical
  interactions. Their persistent routines continue offscreen. Recheck relevance at commit and
  preserve the controller budget while a party is away.

- Lease durable clock work in PostgreSQL, recover abandoned steps, and commit each tick and its
  successor together. Apply migration 014 before upgrading.
- Project each branch's observations in event order across workers and retries. Human commands
  remain available during projection lag, with contextual choice evidence recorded only when ready.
  Delayed observations survive controller changes using current world-scoped projection authority.

- Revalidate private receipt inspection through the existing actor/world-scoped database
  capability function. Separate-process DM revocation now fences new and cached HTTP results
  even when the original API retains a cached grant. Preserve canonical receipt/replay bytes;
  verify actual revocation, current-grant inspection, restart, retries and no duplicate writes.

- Omit private quest/offer projection deltas from ordinary HTTP command receipts, including
  cached retries. Preserve full canonical/durable/replay results and exact-world read-all
  inspection. Verify public/privileged presentation and immutable internal evidence bytes.

- Replace self-reported quest counters with immutable funded objectives and same-transaction
  evidence derived from movement, unique defeats, accepted trades and new offscreen weeding.
  Add controlled physical acceptance/once-only reward claims and manager cancellation/refund.
  Keep private target/source/owner metadata out of public scenes and fiction context; expose
  nearby offers and an owner-only journal through typed console intents. Preserve old receipts,
  reject caller progress/reward terms and verify authority, restart, provenance, replay, rollback,
  worker races and actual desktop/mobile play. Autonomous quest pursuit remains later work.

- Replace caller-priced trades with maker-authorized offers backed by carried item/gold escrow.
  Add controlled posting/withdrawal and manager configuration/cancellation; accept only offer
  references and quantities at physical contact. Reserve both bodies' action time and interrupt
  rest. Refund unused escrow once on cancellation/clock expiry. Expose perceived quotes through
  typed console intents and fiction-safe context; verify parity, rejection, conservation,
  concurrency, restart/replay/rollback and actual desktop/mobile behavior.

- Derive attacks from canonical STR/finesse DEX, training and owned weapon definitions. Add strict
  manager body configuration and ordinary controlled `/equip` intent; preserve legacy scoreless
  profiles until explicit conversion. Show live body abilities and bonuses on the player sheet,
  retain authored card isolation, and emit in-world equipment observations. Verify canonical
  seeded outcomes, authority/forgery rejection, retry, restart/replay/rollback and actual UI.

- Add kernel-seeded initiative and fixed six-second participant windows over the shared clock.
  Enforce the same turn/readiness rules for human and autonomous actions, preserve offscreen work,
  reject overlapping/bypassed encounters and keep private order/seed metadata out of sensory scenes.
  Pin starting ability scores to canonical bodies and reject bound-card stat rewrites. Verify
  actual runner waiting, concurrent transactions, restart/replay/rollback and live console behavior.

- Add controlled `/rest short|long` over canonical activities, shared HP/mana recovery for
  offscreen NPC rest/sleep, uninterrupted thresholds and a daily long-rest interval. Interrupt
  recovery on physical effort/damage, keep authored cards separate and add manager-only resource
  capacity configuration without refills. Verify restart, rollback, replay, parity and live UI.

- Add shared-clock death saves from recorded physical-action seeds, first aid and 0-HP healing.
  Persist save/recovery boundaries with ordinary canonical state, retain retry/replay and atomic
  rollback, and prevent new dead/unconscious sensory grants. Expose `/stabilize` in the console.

- Reject unknown Game Console slash commands with supported-action guidance, preserving the
  draft and making no command request. Verify the rejection in parser/API regressions and the
  two-client PostgreSQL browser journey.

- Synchronize perception-scoped console scenes with bounded visible-tab polling, reconnect,
  obsolete-response protection and explicit unavailable/stale/projection-pending states.
  Preserve background drafts and isolate body changes. Replace the fixed map/four-token cap
  with per-zone presentation and known coordinates; keep interface metadata out of cognition.
  Recognize complete stored-precision observations without rewriting evidence or widening masks.

- Make character assignment prepare an uncontrolled body/binding before atomically publishing
  its roster seat and typed human-control grant. Retry failures without duplicating bodies or
  persona bindings. Reassignment/last-seat removal revoke prior control and fence paused runners
  while preserving physical state/history and independent world roles. Migration013 closes
  stale runtime-owner RLS delegation; shared seats retain their grant.

- Add authorized, bounded timed conditions with independent sources and clock expiry. Preserve
  permanent conditions and make temporary effects participate in existing incapacity and combat
  rules. Expire divine blessings in six-second turns, including deterministic anchoring of old
  grants. Split clock advances at readiness/effect/weather boundaries so offscreen activities,
  routines and social attendance pause for the correct interval. Preserve missing-health guards.

- Keep battlefield camera/control-mode changes outside physical readiness, incapacity and wakeup
  checks while retaining entity-control authorization. Changing presentation never spends or
  resets action time, wakes a sleeping body, or changes body resources.

- Reserve per-body action readiness atomically on configured world clocks, with server-owned
  durations and movement speed costs shared by human and autonomous commands. Expire timed guards
  through clock ticks/advances; preserve retry/restart/replay and suspend waiting stand-ins without
  spending controller budgets. Expose readiness only in the body's own scene. Full initiative,
  condition/blessing expiry and death/recovery remain open C3 work.

- Wire the Player Dashboard to canonical character state with visible-tab polling, manual refresh,
  cancelled obsolete requests and explicit loading/error states. Display live resources read-only
  for bound bodies; retain starting-resource edits for unbound cards and preserve identity drafts
  across polling. Stop denied polling until refresh and clear unavailable resource values.

- Reject HP/status/max-HP/armor/speed changes through authored-card editing after embodiment,
  including administrator requests, and prevent world retargeting through that path. Reject mixed
  resource/identity updates atomically; preserve identity edits, unbound-card setup and existing
  PATCH-null semantics. Live values remain owned by authorized kernel actions.

- Add an owner/world/body-authorized canonical character-state read, with typed allowlisted
  resources, branch/version provenance and no-store success/error responses. Keep the authored
  card unchanged; distinguish unbound cards from unavailable bound bodies. The player sheet now
  consumes this projection and bound-card resource-edit protection enforces canonical ownership.

- Enforce common voluntary-action incapacity checks for movement, speech, defense and other
  controlled commands. Make human wake-by-action transactional for attacks/spells, preserve
  sleeping stand-in suspension, reject healing of dead bodies with stale positive HP, and expose
  incapacity only in the body's own scene to suppress impossible autonomous candidates.
  Registered controlled-command versions carry `+voluntary-body.1`. Full combat time remains open.
  Incapacitated stand-ins wait without spending failure/control budgets, including races during
  proposal generation, and can resume after recovery.

- Wire explicit CHARACTER mode on cognition/decide through the existing trusted scoped proposal
  response and receipt repository. Accept only scope/idempotency, resolve persona/history/actions
  on the server, preserve no-store/retry semantics and leave canonical mutation to submission.
  Keep legacy caller-authored situations/actions confined to privileged EVALUATION mode.

- Allocate physical-action randomness under the branch commit lock from the recorded run seed
  and logical command sequence. Ignore caller roll seeds, preserve policy trace seeds separately,
  and retain private versioned RNG proof for retries/replay. Legacy unseeded runs use zero;
  new runs record zero by default. No schema or frontend deployment change.

- Wire the console's cast alias to registered spell IDs, retain its accessible composer name
  after invalid input, and ship the current production bundle. Pair with the authoritative
  backend contract update; browser tests cover both aliases, health refresh and mobile layout.

- Clear the equipped weapon atomically when its final copy is sold. Keep legacy unavailable
  loadouts readable and omit impossible melee choices while retaining execution validation.

- Make new melee requests target-only and resolve registered owned weapons, body bonuses,
  visibility/reach and conditions inside the kernel. Unify cast/invoke under fixed versioned
  learned-spell rules; validate initial card knowledge/resources without overwriting live bodies.
  Preserve committed old-contract retries across upgrades. Merge/deploy the paired console
  adapter and compiled bundle together with this backend contract change.
  Shared combat time, action-seed allocation, sheet reconciliation and quest evidence remain open.

- Add character-scoped learned-lore retrieval and older-testimony grounding in generated dialogue,
  with pinned starting claims and a shared sensory projection barrier. Keep broad scene inspection
  separate from private mind access in reference and durable modes. Centralize non-sensory event
  suppression and filter global vector lore by world/visibility. No new schema or provider setup.

- Ground controlled relationship classifications in frozen physical evidence and preserve historical
  retry receipts without resetting later vectors. Keep privileged subjective overrides explicit.
- Freeze entity identity/controller/secrets in snapshot 2.1, restore nested trials from exact source
  metadata, and atomically persist scoped trial creation without resynchronizing world grants.
  Add migration 012 for metadata-distinct snapshot identity; legacy 2.0 artifacts remain readable
  but require a new capture for new trial restoration. Complete campaign checkpoints remain planned.
- Restore frozen entity metadata and exact snapshot identity for generic scenario cohorts before
  their first command, preserving distinct trial/run IDs and durable replay across restart.
  Make terminal trial upserts satisfy timestamp constraints before conflict handling, preserving
  original failure diagnostics. Enforce wheel smoke checks even with Python optimization enabled.

- Require source-card authority before NPC association, including locked-record validation and
  retries, and preserve active motivational belief evidence beyond the recent-experience window.

- Add opt-in belief/persona-driven NPC goal selection from pinned CHARACTER traits and validated
  same-body subjective evidence. Heard importance/danger claims can change priorities or interrupt
  work without changing canonical truth; private versioned inputs commit with clock effects for replay.
- Add explicit DM character-card association for existing NPC bodies without a player seat, and
  serialize competing associations while preserving authored card content. No new schema or provider.

- Reject long one-off commitment windows that overlap the first future recurring occurrence,
  in either scheduling order; retain exact touching-window compatibility and atomic rejection.

- Add opt-in bounded daily goal planning: prioritized local work/rest intentions with daily quotas,
  needs and appointments, physical shelter/recovery, blocked-route alternatives and interruption
  recovery. Persist private choices and partial fulfillment through the existing atomic world clock;
  midnight resets intentions without duplicating body resources. No new migration or provider.

- Add opt-in home/work travel, daily sleep windows and joint recurring social obligations to the
  existing world clock. Preserve partial work and actual positions across interruptions and restart;
  blocked routes, injuries, absent partners and food shortages produce causal waits or missed meetings.
- Suspend sleeping character policies without consuming control steps; human actions can wake them.
  Show only inspected physical activity, with future routes, schedules and attendance records private.

- Bind materialized population identities to one canonical body through a typed command with
  transactional source validation. Migration 011 freezes embodied source rows and rejects stale
  legacy transitions; the branch projection owns live lifecycle metadata.
- Add opt-in recurring NPC work/rest/meals, body-owned hunger/fatigue and finite food consumption,
  physical relevance transitions, and inspected eating in the console. Keep partial work across
  lifecycle changes, rain, shortage, incapacitation, worker races, replay and restart.

- Add opt-in persistent branch clocks and a world-runner CLI/Compose service, explicit FREEZE or
  bounded CATCH_UP, pause/stop boundaries and executor epoch/step fencing through atomic commands.
- Add persistent offscreen WEED/REST work, ordered scheduled rain, partial progress/cancellation
  and physical interruptions. Show only inspected current activity in scenes and console rows.
  Reuse existing RLS projections/ledger without a new migration; full population/routines remain open.

- Add optional configurable OpenAI-compatible generated character dialogue after history/persona
  intent selection, with sourced subjective input, typed output, private immutable provenance and
  bounded outage fallback. Leave provider/model/key selection and activation to the operator.
- Add typed one-attack guarding and server-owned ARCANE_BOLT/MEND presets, own-resource perception,
  tactical choice weighting, console commands and initial explicit card mana. Migration 010 extends
  private human evidence without changing old profiles, RLS authority or synthetic exclusion.

- Retain the durable control plane's bootstrap identity after authority reordering; fail closed
  on its loss instead of selecting an unrelated world's actor during synchronization.

- Mask combat details by event-time modality and participant visibility; order validated experience
  before truncating long equal-timestamp conversations to prevent repeated autonomous replies.

- Fixed autonomous scene refresh losing a step when the controller panel remounted during loading.

- Extend trusted character choices to contextual speech intent/volume, known-threat basic melee
  and withdrawal, driven by comparable human history plus pinned persona/card fallbacks. Preserve
  legacy movement profiles; freeze separate choice provenance in proposal receipts.
- Add migration 009 private append-only RLS choice evidence committed atomically with actions.
  Add physical combat perception and canonical observation ordering across timestamp ties/restarts.
  Open-ended dialogue, spells, full tactics and narrative planning remain unfinished.

- Wire comparable human movement history and pinned persona/card tendencies into character advice
  and the unattended runner. Add private content-addressed behavior profiles and conflict notices.
- Migration 008 records perception-scoped human movement evidence atomically with canonical actions;
  distinguish server-derived input origin from execution authority and exclude policy/operator
  actions from learning. Speech/combat imitation and complete timeline restoration remain planned.

## Spatial epistemics

- Added explicit `entity.act` authority and controlled-body requirements for embodied commands.
- Added a shared deterministic event finalizer and entity-scoped frozen `PerceptionGrant` records.
- Added migration 003 with append-only perception grants, belief evidence, provenance links, RLS,
  and retry-safe durable persistence.
- Added grid zones, portals, occluders, sight, sound, event-time context hashes, and embodied speech.
- Replaced the Player Game Console's canonical map/event reads with a viewpoint-scoped scene and
  observation feed; distant entities degrade to anonymous presences rather than leaking details.
- Added testimony provenance and selective memory consolidation so routine movement does not fill
  permanent memory.

This file records the current TableTop DM product line.

## Unreleased

### Planning

- Added a code-mapped autonomous campaign checklist covering world progression, player-history
  stand-ins, controller handoffs, open parties, timeline revision, story direction, and AI DM tools.
  The checklist describes planned work and does not add runtime functionality.

### Gameplay

- Added explicit human/autonomous/pause handoffs and a bounded character runner with dedicated
  AGENT authority, typed kernel submission, stale-controller epoch fencing, atomic step/budget
  accounting, durable retry/restart recovery, and Game Console controls. Migration 007 stores
  private controller state and append-only handoff provenance; transitions are never sensory.
  Managed commands must carry their observed epoch. The current runner uses local basic movement
  utility; narrative planning, world-clock activities, and player-history imitation remain planned.

- Hardened pre-run foundations: card revision ability scores are immutable and saved-character
  reads are defensive copies; spawning retries reach the kernel receipt lookup; snapshot trials
  exclude bodies created after their snapshot. Membership join timestamps honor normalized status.

- Added trusted CHARACTER proposal advice from pinned identity and perception-scoped experience.
  Server-owned seeds/actions and a sensory projection barrier feed local deterministic policy;
  migration 006 stores immutable private retry receipts and decision traces atomically. Advice
  leaves human control and canonical state unchanged; execution still requires a normal kernel
  command. Automatic scheduling, player-history imitation, and broader actions remain planned.

- Added migration 005 for immutable private authored-card history and version-pinned character
  persona/body/mind bindings. Initial roster assignment creates a missing binding; later edits
  require explicit successor adoption. Atomic/CAS persistence preserves existing experience and
  runtime selection. Trusted context exposes only pinned self fiction, with starting claims kept
  separate from learned facts. This does not yet enable unattended decisions or player imitation.

- Added a versioned server-owned basic movement-attempt catalog to authorized character context.
  Choices use perceived self state and world-scoped capabilities/body control, without class or
  protagonist restrictions or hidden-obstacle filtering. Kernel validation remains authoritative;
  inspect-only reads offer no executable choices. Full character decisions and the campaign runner
  remain unavailable pending identity, history, knowledge, and controller wiring.

- Fixed automatic scene refresh after accepted Game Console actions, including delayed external
  observation projection. The feed renders each perceived source event once; world/viewpoint
  switches clear local state and discard late responses. Accepted actions remain visibly accepted
  if a scene read fails, and retry only reloads the scene. Durable scene/context reads use fresh,
  request-local RLS snapshots without replacing the shared projector cache.

- Added validated character backstory, motives, values, bonds, character secrets, and starting
  knowledge claims to card creation/import/editing. Private sheet storage and a deterministic
  current-content version survive restart. Authored claims do not enter world truth or minds;
  historical card revisions and persona/mind/body bindings are supplied by migration 005.

- Added read-only embodied character context grounded in same-branch source events and frozen
  perception grants; shared its scene reader with the Game Console. Operator records, unbacked
  beliefs, and caller-authored memory summaries cannot add model-facing facts.
- Fixed current scene reads to honor blindness and sight acuity while retaining self/perception
  history; model-facing beliefs use consistent local subject references instead of kernel IDs.
- Restricted caller-authored cognition to privileged simulated-playtester evaluation and rejected
  live character requests until identity/context/action wiring is complete. Context reads currently
  expose only the basic movement-attempt catalog; authored backstories and the runner remain unfinished.
- Rejected non-finite/overflowing persona distribution weights and totals with the intended
  feasibility error before seeded sampling.

- Added explicit character and simulated-playtester persona purposes. Character compilation and
  prompt trait selection exclude player/interface metadata and onboarding/GM behavior; existing
  evaluation defaults retain historical persona IDs and version hashes.
- Added migration 004 to persist purpose and enforce matching blueprint/compiled-profile purpose,
  with clean-install, previous-schema upgrade, rollback, and restart checks. Added API purpose
  selection; autonomous live context and lore filtering remain planned campaign work.
- Cleared stale roster character choices and errors immediately on user/role changes and blocked
  player saves while the selected user's lookup is pending.

- Added explicit Player/Co-DM selection and playable character assignment to the DM roster,
  including existing-member updates, authorized character-summary lookup, and rejection of
  missing, wrong-owner, and cross-world character assignments.

### Security

- Enforced controller/world mind-inspection checks in reference mode as well as durable storage.
- Corrected frozen sensory grants for zero/invalid acuity and strongest-path sound propagation;
  new grants record resolver version `grid-spatial-perception-1.0.1`.

- Applied browser write-origin checks to public login before creating a session.
- Rejected differing compiled-profile retries at an existing immutable persona/version/compiler key.

- Bound every command, event read, cognition decision, observation, and mind inspection to the
  actor of the signed-in account. Previously the actor came from the request, so any authenticated
  account could act and read as any actor, including the administrator's, and the ledger recorded
  the impersonated actor rather than the caller. Only the operator/automation token may still name
  another actor.
- Required the Administrator role to list or create simulation actors. An actor carries world
  capabilities, so an unguarded `POST /api/v2/actors` was a capability mint.
- Added world-scoped authorization to every control-plane read, including
  `GET /api/v2/branches/{branch_id}/replay`. Worlds, runs, branches, snapshots, and events now list
  only the caller's worlds; roles are never unioned across worlds.
- Provisioned simulation authority from product roles through
  `identity.repository.kernel_authority`, so a `DM` or `PLAYER` grant reaches the kernel on the
  account's next sign-in in both reference and durable modes rather than only after a restart. A
  Player receives `world.read`, `action.propose`, and `action.commit`, and no entity control.
- Moved `/api/v2/trials` behind the Administrator boundary, replacing a routeless
  `/api/v2/experiments` prefix that guarded nothing.
- Excluded disabled administrators from the final-administrator guard, which could otherwise be
  satisfied by an account that cannot sign in and leave an installation with no usable
  administrator. The last administrator who can still sign in can no longer be disabled either.
- Stopped failed logins during an active lockout from extending it, and reset the failure count
  once a lockout lapses. Previously an attacker could hold any account locked indefinitely by
  guessing at the username, first by extending the window and then by re-locking it with a single
  attempt per window.

### Testing

- Added `tests/integration/test_durable_authorization.py`, asserting that session-bound actor
  binding, world scoping, event visibility, and actor minting reach the same outcomes against
  PostgreSQL and row-level security as they do in reference mode.
- Marked `tests/unit/identity/` and `tests/unit/domains/` with `pytest.mark.unit`. Neither carried
  a marker, so `pytest -m "unit or contracts"` — the fast gate and the CI lane — silently skipped
  all eight tests in them.

## 2.0.0 - 2026-08-20

### Platform and identity

- Added secure account login with HTTP-only sessions, forced first-login password replacement,
  password policy enforcement, failed-login lockout, and append-only identity audit records.
- Added global Administrator access and world-scoped Dungeon Master and Player roles, including
  combined DM + Player access.
- Added Administrator account management for creation, editing, enable/disable, deletion,
  password reset, global roles, and per-world roles.
- Added profile settings for display/legal name, email, date of birth, pronouns, timezone,
  locale, biography, avatar URI, password changes, and sign-out.

### Tabletop workspaces

- Added a Player Dashboard for saved characters, character statistics, alive/dead status,
  deterministic generation, manual building, and JSON template import.
- Added a Dungeon Master workspace for hosted games, game status, rosters, player-character
  assignments, session scheduling, safety notes, house rules, and private DM notes.
- Added a typed Game Console for dialogue, movement, combat, and spell proposals against
  canonical public state.
- Added the Control Plane, Persona Studio, Population Studio, Scenario Lab, Run Inspector, and
  Calibration workspaces with role-aware navigation.
- Added engine-neutral Tactical, Third Person, and First Person control-mode contracts over one
  battle state, five persistent squad-AI orders, unified aggregate/direct weapon statistics, and
  perception-scoped renderer/input ports for a future external engine.

### Simulation kernel

- Added a domain-neutral world/run/interaction kernel with world-scoped actors, capabilities,
  controlled entities, typed commands, deterministic handlers, atomic projections, append-only
  ledgers, visibility, snapshots, isolated branches, replay, and reviewed promotion.
- Added tabletop domain commands for entity creation, dialogue, movement, combat, magic,
  economy, factions, divine effects, quests, content rating, and onboarding.
- Added a modular 80-dimension persona fabric with dependencies, constraints, seeded generation,
  validation, provenance, immutable versions, compilation, and bounded prompts.
- Added subjective cognition with observations, beliefs, memories, relationships, reflexes,
  utility scoring, bounded GOAP planning, runtime assignment, and typed deliberation.
- Added statistical, materialized, and active population layers using Parquet, DuckDB, and
  PostgreSQL lifecycle projections.
- Added immutable scenarios, trial execution, resumable jobs, normalized verifier facts,
  metrics, cohort reports, comparison, calibration review/promotion, and opt-in telemetry.

### Durability and security

- Added PostgreSQL schemas for simulation, identity, tabletop portals, artifacts, personas,
  cognition, populations, and experiments.
- Added Redis/RQ experiment queues, Qdrant readiness and semantic-lore integration, and a shared
  content-addressed artifact volume.
- Added forced row-level security, least-privilege runtime credentials, append-only evidence
  triggers, composite world/branch/run keys, actor transaction context, and secret entity-state
  controls.
- Added durable replay bases, idempotent command receipts, transactional outbox records,
  restart hydration, population transition history, scenario/job/trial/report restoration, and
  consent-aware telemetry deletion and retention.
- Added generated local secrets, loopback-only published ports, browser session authentication,
  and a separate automation operator token.

### Delivery and verification

- Added a multi-stage, read-only, unprivileged production image and Docker Compose topology for
  PostgreSQL, Redis, Qdrant, migration, API, and worker services.
- Added deterministic unit and contract tests, real PostgreSQL/Redis integration tests, React
  component tests, production bundle checks, wheel-runtime verification, and Playwright journeys.
- Added CI quality, integration, frontend, image, browser, and tagged GHCR publication lanes.
- Added complete architecture, API, operations, testing, network, and agent-maintenance guides.

### Constitutional guarantees

- Models never own world truth.
- Persona identity is independent of the runtime executing it.
- Canonical truth, observation, belief, memory, and narration are distinct records.
- Every stochastic or model-assisted decision records reproducibility provenance.
- All canonical mutations pass through typed validation and authorization.
- Experiment branches cannot mutate canonical state.
- Verifiers emit normalized facts with evidence, not persuasive prose.
- Synthetic outputs are hypotheses, not human ground truth.

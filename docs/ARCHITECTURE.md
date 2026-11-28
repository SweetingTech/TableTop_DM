# Architecture and invariants

## System shape

Party membership belongs to embodied entities. The party, invitations, and linked departure
events are branch projections. Each member consents through the existing body authority.
The scene presents the charter and membership to members and presents pending invitations
to their intended recipient. Roster and controller access still require explicit authorization.
The character runner and offscreen planner share the pinned character profile reader. It obtains
character-purpose traits from the immutable blueprint, preserving motive choices after restart.
The party leader records the shared waypoint. Each member chooses whether to follow it and moves
through the existing controlled-body rules. Shared cache contents come from explicit deposits at
the cache site. Character knowledge still comes from each body's frozen observations.
Quests store their authored contacts, complete approaches, and funded reward in the branch projection.
Responsibility can pass between consenting bodies. The new holder inherits verified progress and
the same escrow from the original giver.

The character action catalog offers MEND for a currently visible, wounded body in reach that the
character observed healing them. A witnessed attack against the character removes that target
from the support choices. The private choice profile compares human actions with comparable
healing options and retains the source event IDs and confidence.

Character recap uses private branch revision boundaries captured under the normal handoff lock.
New command ledger rows carry the exact committed revision. A recap matches same-run commands
within the most recent autonomous interval and renders only their validated frozen observations.
The typed console receives the resulting narration entries.

An opted-in player's authenticated console renews its private controller deadline under the branch
lock. The runner checks expired deadlines and uses the normal handoff transaction after rechecking
the current owner, grants, run status, and epoch. A reconnect keeps human control if renewal
arrives first. After an automatic handoff, the player explicitly takes control at the new epoch.
Durable presence deadlines use the PostgreSQL clock for creation, renewal, and expiration.

Comparable human speech evidence records a bounded cadence category with the accepted source event.
The private choice profile uses a majority of comparable replies and pins the supporting events in
the decision receipt. The dialogue provider receives the style category along with the scoped
fiction and policy-selected intent. The typed speech command carries the resulting utterance.

Decision origin is private command provenance. The HTTP boundary derives human input, accepted
advice, or operator origin. The runner uses the player body type and its world-scoped human
controller to identify stand-ins, and the private trace to distinguish NPC policy from model
assistance. The controller epoch and agent grant still authorize execution. Origin labels stay
outside sensory events.

The durable clock scheduler keeps one outstanding step per canonical branch in
`sim.world_due_work`. Workers sort due candidates by deadline and branch ID, then compete for a
lease scoped to the assigned executor. The existing branch transaction validates the lease and
publishes the clock, receipt, event, outbox and successor together. Completed steps remain in
the command ledger.

Subjective projection claims only the first unpublished world event on each branch topic. An
earlier claimed event or retry blocks later events on that topic while other branches can
continue. Claim tokens and the outbox row lock fence competing projectors. The character
proposal service still requires each of the body's frozen observations before deciding.

The character runner can replan after a typed action fails against a branch revision newer than
its proposal. It starts a new private attempt at the same controller epoch and step. Reference
and durable submission validate that attempt under the branch lock, so delayed workers cannot
commit a superseded proposal. A rejected attempt publishes no world event or evidence.

Character plans live in private decision receipts. The runner continues a plan only after it
finds an accepted predecessor command in the same world, branch, run, body, controller epoch,
and pinned binding. Fresh perception and the body's own needs determine the next available
action. The controller's existing due time schedules the next check.

Optional model deliberation receives a frozen fiction view and names from the engine's eligible
action list. Anonymous references preserve relative locations and known characters. A scoped
PostgreSQL advisory lock serializes the same proposal key while the model
responds. World writes keep their separate run and branch locks. Before persisting a new proposal,
the service rechecks the live actor scope and latest pinned binding. The receipt and its typed
provenance commit together.

Conversation scheduling recovers its next cue from ordered, masked same-run speech observations
and the controller's persisted due time. Reply receipts link that cue to the typed speech proposal.
Its committed speech event becomes the next source of conversation history. The model sees an
anonymous reference to the cue and the chosen language and volume.

Durable private-receipt presentation uses the existing `sim.has_world_capability` function in an
actor-scoped transaction. This bounded read observes current exact-world grants without hydrating
all world state or trusting the API's cached authority. A separate-process DM revocation applies
to new and cached HTTP receipts; the committed command result remains unchanged.

HTTP receipt presentation omits private quest/offer projection deltas for actors without
world-scoped `world.read.all`. This pure projection never changes canonical receipts or replay
inputs; public action results and scenes remain available without revealing hidden objective
targets or source provenance. Cached retries pass through the same authority-based presentation.

Quest contract definitions and their funded reward reserves live in `tabletop.quest_contracts`.
Definitions are immutable; each accepted contract records one body owner and progress from
authorized same-transaction MOVE, DEFEAT, TRADE or clock-owned WEED outcomes. A handler wrapper
derives bounded progress and private source command IDs after ordinary physical rules resolve,
then commits the physical result, quest evidence, receipt, event and outbox together. Defeat
targets count once. Claimed/cancelled contracts retain terminal audit state but consume no active
quota. Other characters see only nearby public offers; only an owner's scene exposes its journal.
Neither public views nor fiction context reveal target IDs or private source/provenance records.

Trade consent is canonical, versioned `tabletop.trade_offers` state. SELL offers reserve items;
BUY offers reserve gold from the maker's free body inventory. The reserve remains in that body's
physical custody, so acceptance requires contact with its capable, perceived maker. Takers submit
only an offer reference and quantity. Exchange, remaining reserve, both bodies' readiness and
rest interruption commit with the same command/event/outbox transaction. Cancellation or clock
expiry returns the remaining reserve and removes active state, preserving append-only history.
Scenes expose quotes only at contact range; cognition replaces offer IDs with fiction references.

Canonical scores/training and versioned weapon definitions drive attack profiles in
`domains/tabletop/rules.py`. Typed manager body configuration sets definitions without changing
resources; controlled equip is an ordinary physical action over owned inventory. A score-bearing
body ignores obsolete flat attack/damage fields. New bindings pin starting scores/proficiency;
legacy scoreless bodies keep their explicit profile until authorized conversion. Live sheet
projections expose current own-body scores and bonuses without rereading authored physical stats.

Initiative is one branch projection, `tabletop.encounters`, over the existing world clock.
Manager-only typed commands roll server-seeded canonical DEX scores and start/stop the fixed
order. No client supplies rolls, bonuses or turn duration. The ordinary controlled-action wrapper,
scene readiness, offscreen activity engine and character runner share the same turn wait. Physical
conflicts serialize in the existing atomic branch transaction; models remain proposal-only.
Stopping removes active encounter state without deleting ledger evidence or refunding resources.

Rest is an activity over the canonical clock and body resources. `domains/tabletop/rest.py`
owns versioned thresholds, uninterrupted progress and the long-rest interval for both controlled
bodies and offscreen NPC routines/sleep. The typed rest intent cannot supply duration, healing
or resource limits. Manager-only capacity configuration is distinct from current resource mutation;
authored cards never overwrite either. Clock transitions commit activity, HP, mana and cooldown
with the ledger/outbox. Successful effort/damage appends rest interruptions in the same command.

Defeat saves live in the branch's typed `tabletop.vitals` projection. Damage commands create
them from the same trusted physical-action seed used by both kernel repositories. Clock
boundaries resolve indexed rolls and recovery on a private working state; bodies, vitals,
clock, event and outbox commit together. Healing removes pending saves only for a living body.
Sensory resolution freezes awareness at event time; dead and unconscious bodies receive no new
grants. Human scene introspection still shows one's own body status without exposing save seeds.

Roster preparation creates an uncontrolled canonical body and pins its card/persona without
publishing a seat. Finalization composes the portal seat with a typed controller mutation in
one actor-scoped PostgreSQL transaction. Reference mode enlists seat publication before atomic
command publication. Neither path grants a model or client direct canonical write access.
Controller identity/history stay immutable; removing a seat pauses the runtime, advances its
epoch and revokes body/runtime-owner access. Shared seats retain their existing grant.

Console synchronization polls only authorized scenes, fences obsolete requests and rejects older
projection versions. Observations may advance at the same version. Map configuration is a
separate typed presentation command/projection; only perceived-zone maps and experience readiness
are added to HTTP interface responses. Character scene contracts and cognition never receive
these interface fields. Durable readiness accepts complete same-event/body/mask/time evidence at
the database's stored confidence precision, retaining original IDs and frozen visibility.

Timed conditions are typed records stored separately from a body's permanent condition list.
Each source retains its creating command/run and absolute simulated expiry. Existing rule
evaluation unions active timed sources with permanent conditions; expiry removes only the due
source. The authorized clock works on a private copy and splits elapsed progression at effect,
readiness and weather boundaries before emitting ordinary canonical deltas. This preserves
split-versus-whole physical outcomes and prevents work or joint attendance during incapacity or
reserved action time. Private source metadata is not added to player scenes or live sheets.

Configured branch clocks govern controlled-action readiness through the domain wrapper
`action-time.1`. Successful effects and the `tabletop.action_time` reservation share one kernel
transaction. The wrapper reads body speed and versioned rules, never client duration values.
No action advances global time; the existing clock runner/authorized advance does so, preserving
offscreen work. Branch locking serializes competing commands for one body; unrelated bodies can
act at the same simulated instant. Failed attempts leave neither effects nor reservations.
Readiness is physical branch state across run reconfiguration, snapshots, trials and restart;
new actions require the clock to belong to their current run. Only the observer's own readiness
is included in its scene. This is a sequential action-time model, not a full initiative system.

An embodied character's physical resources are owned by its canonical body. Portal card updates
cannot change HP/status/max HP/armor/speed or retarget that bound card's world. This applies to
owners and administrators alike; card ownership does not grant an alternate canonical write path.
Identity edits remain authored/versioned separately, and unbound cards still author initial values.

Character live-state reads project the canonical branch's physical body into a typed allowlist;
they do not synchronize wounds/resources back into authored cards. HTTP composition checks card
ownership, current world access and body inspection authority, then freezes the reference read
or uses a fresh durable snapshot. Card identity/version and body projection/version remain distinct.

Registered controlled commands share the `voluntary-body.1` capability/wakeup policy. Human
wakeup is evaluated in an isolated awake copy and committed only with a successful result.
Incapacity rejects before handler execution; private conditions are not inferred for other bodies
through scene status. The own-body scene can suppress impossible stand-in action candidates.

The generic cognition API dispatches explicit CHARACTER requests to the same trusted response
builder and append-only proposal receipts as the entity-scoped character endpoint. It accepts
scope/idempotency only, so identity, scene, learned knowledge and action candidates remain
server-derived. Caller-authored evaluation is an explicit privileged playtester path.

Physical-action RNG is allocated by the commit boundary from recorded run seed and next branch
projection version, after original-receipt lookup and under the same transaction/lock as mutation.
The private result records `logical-action-rng-1.0.0` provenance. Policy-selection seeds and traces
remain separate; event-time physical masks exclude RNG provenance from character observations.

The system separates human identity, simulation authority, canonical state, subjective minds,
large populations, and experimental evidence.

Versioned tabletop action rules resolve melee statistics from the current body and its owned
weapon, and spell effects from registered definitions plus body-owned learned spells/resources.
Human and autonomous proposals use the same typed handlers. Scope-checked committed receipts
are loaded before current request normalization so a contract upgrade preserves old retries;
new keys must satisfy the current strict schema. Replay consumes recorded outcomes.

```mermaid
flowchart TD
    UI[React workspaces] --> AUTH[Identity and session boundary]
    CLI[CLI / automation] --> API[Flask API]
    AUTH --> API
    API --> KERNEL[Simulation application and command bus]
    KERNEL --> DOMAIN[Tabletop command registry]
    KERNEL --> STATE[Branch projection]
    KERNEL --> LEDGER[Command / event / outbox ledger]
    LEDGER --> MIND[Cognition pipeline]
    STATE --> SNAP[Snapshots and trial branches]
    SNAP --> LAB[Scenario and evaluation lab]
    PERSONA[Persona fabric] --> MIND
    PERSONA --> POP[Population engine]
    POP --> LAB
    LAB --> METRICS[Verifier facts, metrics, reports, calibration]
```

`world_id`, `run_id`, and `interaction_id` are kernel terms. Campaigns, sessions, and encounters
are tabletop interpretations rather than core primitives.

## Identity, roles, actors, and capabilities

Human access has two role scopes:

- `ADMIN` is a global platform role.
- `DM` and `PLAYER` are grants tied to a specific world.

Every account has an actor ID. The identity repository translates role changes into explicit
world/actor authority rows used by the simulation kernel and PostgreSQL RLS. A grant in one
world never authorizes another world.

Actors are `HUMAN`, `AGENT`, or `SYSTEM`. Their world-scoped roles, capabilities, and controlled
entities authorize operations such as:

- `world.read` and `world.read.all`;
- `entity.control` and `entity.read.secret`;
- `entity.act` for acting through explicitly assigned embodied entities;
- `action.propose` and `action.commit`;
- `run.branch`;
- `mind.read.all` and `mind.write.all`;
- `metric.evaluate`;
- `canonical.promote`.

The API checks product roles; the command bus checks simulation capabilities and controlled
entities; PostgreSQL repeats protected-state checks with forced RLS.

## State, commands, and events

World time and initial offscreen activities use existing canonical branch projections and the
same atomic command/event/outbox transaction. Typed clock configuration pins an explicitly granted
AGENT and an epoch; ticks compare epoch/step while the branch is locked. All workers use one logical
retry key per step and fresh durable snapshots. Clock pause fences unattended character actions at
commit. Operational UTC/downtime policy stays separate from integer simulated seconds.

Scheduled weather splits elapsed activity work at deterministic boundaries. Initial WEED/REST
rows own progress; canonical bodies alone own resulting work/fatigue. Viewer presence has no effect.
Scenes expose inspected current activity only. Configuration/ticks/pending work are operational
records with no sensory emission. Population lifecycle coupling and a generic leased queue remain
separate; see [the workflow](API_AND_WORKFLOWS.md#world-time-and-offscreen-activities).

Scoped narration is a read-side renderer for committed physical events. Operator narration
uses selected facts from the event ledger. Spectator and character narration use the body's
masked observation and frozen perception grant. The append-only presentation store retains
actor, audience, run, and source lineage. Its text never enters replay or character cognition.

Autonomous recovery derives from committed commands in the current controller epoch and the
character's witnessed speech lineage. It narrows the current plan's candidates before local
or model-assisted selection. The controller reports a pause when every candidate repeats the
stall, and accepted recovery decisions retain private evidence of which choices were skipped.

Character proposal persistence, binding changes, and controller handoffs serialize run writes
with `FOR NO KEY UPDATE`. Canonical branch commits can concurrently check their command and
event foreign keys against that run. The branch lock still fences changes to physical state.

Generated dialogue is an optional expression layer after deterministic intent selection. An
injected provider receives sanitized identity and sourced subjective experience, never simulation
authority or profile/controller metadata. Its typed text/source response replaces only speech
text; claims stay empty. Private immutable receipts freeze output hashes, supporting events and
model/prompt versions. References bound evidence but cannot certify semantic truth. The kernel
remains the sole canonical mutation path, including fallback speech.

Guard and spell invocation are registered deterministic commands. The server owns guard benefit
and spell effect/cost/range. Candidates use perceived own resources and known visible threats.
Migration 010 extends new human choice evidence without rewriting old profiles or learning from
autonomous output.

Speech/combat choice profiles are separate from the immutable movement-profile schema. They
freeze their own content-addressed version and private human source IDs inside proposal receipts.
New choice evidence and legacy movement evidence commit in one kernel transaction through an
injected bundle sink. Raw historical utterances are not preference payloads or generated replies.
The trusted context orders eligible observations by canonical source-event sequence, so equal
wall-clock timestamps cannot reverse a conversation across restart.

Only a validated perceived attack against this body marks a currently visible body as a threat.
The catalog offers melee, guard, fixed spell attempts, movement and speech intents. A
fresh conversational/attack turn permits one reply; the character's own reply cannot keep itself
talking. Combat emits frozen physical observations; controller and profile metadata never do.

Human movement preferences are operational evidence, separate from character memory and canonical
truth. An injected builder captures only perception-scoped pre-command features while the kernel
holds its mutation lock. The durable adapter commits private append-only evidence with its source
command/event/outbox; failure rolls back the entire action. Reference receipts retain the same
internal evidence and publish it after commit. Evidence never enters sensory event payloads.

Input origin is independent of execution authority: the HTTP boundary derives HUMAN_INPUT,
POLICY_ADVICE, or OPERATOR; old/direct commands default to UNSPECIFIED. Only untraced HUMAN_INPUT
movement through the bound human owner's body trains this first policy. Profiles are deterministic,
content-addressed, keyed by player actor/character/exact world-branch-run-body, and frozen inside
private proposal receipts. They do not change the pinned persona or introduce account/control facts
into character fiction. Broader language, risk, relationship and tactical inference remains planned.

Authored character identity is private portal data, distinct from account identity, persona,
embodied entity, and mind. Its typed backstory/values/knowledge claims persist in the existing
character sheet and receive a deterministic current-content identifier. They do not create
canonical facts, observations, memories, or runtime assignments. Private immutable revisions and
explicit live bindings pin the authored identity independently from experience and runtime.

`BranchState` contains named projections, a monotonically increasing version, and a stable
SHA-256 state hash. Supported delta operations are `SET`, `MERGE`, `DELETE`, and `INCREMENT`.

Command definitions declare a stable name/version, typed input, typed output, required
capabilities, eligible branch kinds, and a deterministic handler. The in-memory adapter applies
deltas to a copy and publishes only after success. The PostgreSQL adapter locks the branch
projection and commits the projection, command, event, and outbox in one transaction.

`EventEnvelopeV2` carries world/branch/run/interaction lineage, actor and embodied entity,
visibility and observation scope, correlation/causation, idempotency, seed, decision trace,
persona/policy/prompt/model versions, tags, payload, and creation time.

Command handlers may declare a deterministic sensory emission. A shared event factory resolves
that emission against pre/post-command spatial state and returns the canonical envelope plus
entity-scoped, event-time-frozen perception grants. Raw event authorization (`visible_to`) is not
physical witness membership. See [Spatial epistemics](SPATIAL_EPISTEMICS.md).

## Canonical state, snapshots, trials, and replay

An operator checkpoint hold serializes with the normal canonical branch commit lock. It pins the
projection hash, command ordinal and event prefix, then prevents new actions and controller
transitions. The projector can drain existing outbox work. Readiness requires no unpublished
row in the held branch's prefix, including work leased by another projector. The hold is durable
operational control and stays outside story events and character observations. A matching release
resumes the normal command and scheduling paths.

Private campaign capture reads that ready boundary in a repeatable-read transaction with the
branch locked. It gathers canonical projections and entity metadata, branch-local minds and
population sources, runtime assignments, logical schedules, and pinned versioned dependencies.
The archive names reconstruction inputs for derived narration and knowledge. Its database receipt
binds the same hold and digest. The metadata route verifies the archive bytes, the exact
event, command, and physical perception prefixes, and the referenced file artifacts.

Automatic checkpoint rules are versioned world-operator records. A deferred outbox trigger
records the originating event and acquires a hold at the command transaction's final cut before
another command can commit. The existing world runner reads ready dispatches, checks the stored
operator's current authority, publishes the named archive, and releases that exact hold.

Checkpoint retention applies a versioned branch policy to released scheduled archives.
The repository serializes pin changes, retirement, and archive reads. It verifies the
files that satisfy the keep count before the database commits retirement. File cleanup
starts after that commit and can be retried from the persisted retirement records.

Every durable world has an explicit canonical continuation pointer. Its epoch identifies
an immutable lineage entry. World hydration and automatic clock work use that pointer,
and a separate trial continues to use its own snapshot and proposal authority.

Revision preparation verifies the checkpoint against that pointer and writes a private
plan. The plan records an idempotent identity, provenance, and a digest of the paused
candidate derived from the archived projection. Prepared plans protect source archives
from retention using the same branch fence as file cleanup.

The rewind input builder rekeys historical events, their frozen perception grants, and
the archived observations, beliefs, memories, and relationships for the successor branch.
It preserves body identity and witness-specific payloads and binds the result to the plan.

Activation holds the current branch and waits for its outbox. A single transaction
builds the successor from the verified archive, initializes its replay baseline, and
switches the canonical pointer. A deferred check rejects an incomplete transaction.
Private event lineage links retained records to the previously experienced events.
Encounters, offers, recovery, action reservations, and timed conditions rebind to the
restored run identities. The restore contract version commits their result to the plan hash.
Command submission resolves a newly restored run from durable storage when the receiving
API process has an older in-memory view.

The typed correction command binds an exact restored run, continuation epoch, and
projection hash. Its ledger receipt and projection changes commit together. A durable
guard checks paused successor scope under the current actor's world grants. The private
reason stays in the operator command ledger. Resurrection uses the ordinary spatial
perception pipeline so each witness receives the factual view it can actually see.

A prepared correction runs through the durable command repository inside the activation
transaction. The database defers validation until commit and requires the expected
command, event, and corrected projection before publishing the continuation.

Resume is a separate typed transaction. It rechecks the active epoch, reauthorizes the
archived controller modes, and configures the restored clock through the normal command
repository. The run status, fresh leases and resume receipt become visible together.

Each world has one canonical branch. A snapshot is a deterministic gzip artifact containing the
projection, command boundary, contract version, and content hashes. Contract 2.1 also freezes each
entity's identity, controller and secret metadata at that boundary. Public body resources remain
only in the projection. Snapshot identity includes metadata; replay state hashes still identify
projections. Migration 012 permits distinct artifacts with the same projection and command boundary.
Trial branches load an
immutable snapshot and preserve logical entity IDs beneath a different branch-scoped key.

Durable capture locks branch then projection, reads entity metadata and command boundary, and
persists artifact metadata plus manifest in one transaction. Trial creation persists only that
trial's branch, projection, entities and run; it never resynchronizes world grants. Memory publishes
after commit. Nested trials restore the selected snapshot's metadata, never today's canonical
entities. The exact base snapshot ID survives hydration even when projection hashes match.
Legacy 2.0 artifacts remain readable for replay; new trial restoration from them fails closed
because their historical entity metadata is unavailable. Minds, evidence, population source stores,
controller assignments and retrieval indexes still need complete checkpoint support.

Trials write only their own projection and ledger. Canonical promotion is a separate reviewed
command requiring:

- a real source trial in the same world;
- `canonical.promote` and `action.commit`;
- explicit consequence deltas and a human review note;
- the expected current canonical state hash.

Replay starts at the latest valid branch snapshot and reapplies subsequent durable command
records. Each resulting hash must equal the committed hash.

## Battlefield control and presentation

Tactical, third-person, and first-person play are camera/input modes over the same branch state.
The commander, followers, enemies, weapons, health, upgrades, objectives, and encounter ledger
are never duplicated for a perspective change.

`domains.tabletop.battlefield` provides typed mode and squad-order commands, shared weapon
contracts, an authorized `BattlefieldFrame`, and renderer/input protocols for a future external
engine. Tactical mode maps to formation authority; third- and first-person map to direct commander
authority. Squad AI remains active in every mode.

Presentation is downstream of knowledge. The frame builder requires entity IDs already approved
by perception/visibility policy, so a tactical camera cannot reveal hidden canonical state. A
future browser or 3D engine consumes frames and submits input envelopes; it never receives a
mutable world projection.

See [Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md).

## Persona fabric

The schema registry loads 80 dimensions from four YAML packs:

- `core`: cognition, personality, values, communication, social style, risk, and habits;
- `world`: species, culture, religion, class, education, occupation, and faction context;
- `tabletop`: experience, rules familiarity, play preferences, optimization, and metagaming;
- `accessibility`: reading, visual, motor, cognitive-load, and interface preferences.

Dependencies and constraints form a graph. Generation uses a declared schema version, generator
version, ruleset version, seed, fixed dimensions, and optional weighted distributions.
Provenance records the source of each field. The compiler turns deep traits into policy weights,
starting beliefs/goals/relationships, routines, capability modifiers, retrieval filters, and a
bounded prompt summary.

Blueprints and compiled profiles carry a `CHARACTER` or `SIMULATED_PLAYTESTER` purpose. Purpose
is part of character generation/version identity and cannot be overridden during compilation.
The character compiler allows only core/world dimensions into deep traits and prompt selection;
it does not seed player goals, GM trust, interface capabilities, or evaluation retrieval filters.
Initial character goals and knowledge require authored identity and experience in later campaign
wiring. Playtester behavior remains the default for existing callers. Legacy playtester UUIDs
and hashes omit the default purpose field to preserve immutable historical identities.

## Subjective cognition

The tabletop perceived-scene reader lives in `domains/tabletop/spatial/service.py` and is shared
by scene and character-context reads. `cognition/context.py` assembles an immutable context using
injected source-event and frozen-grant readers. Observation payloads must remain within both the
recorded mask and the original physical grant; beliefs need matching visible claims, and memory
summaries are grounded again in the same observation. Operator-tagged and other-branch evidence
is excluded. The model-facing situation omits account/control and timeline/ledger metadata.
Context reads do not mutate minds or the world. Legal action providers are a server injection
point; the HTTP route injects the [tabletop basic action provider](../domains/tabletop/character_actions.py).
It uses only the authorized perceived scene and world-scoped actor authority, offering movement,
speech and fixed tactical attempts without probing hidden truth. Kernel validation decides outcomes.
Caller-authored evaluation is restricted to privileged playtesters; live characters use their
pinned trusted context through the proposal service and bounded runner.

Character knowledge is a derived, read-only view in `cognition/knowledge.py`. It indexes validated
same-branch observation text before recent-window trimming, plus pinned starting claims. It never
queries the global lore catalog to fill gaps. Durable requests rebuild it from actor-scoped stores;
there is no second mutable knowledge database. Retrieval and generated dialogue share that view,
preserving source-event/card provenance privately and exposing only fiction in model inputs.
Broad scene authority is separate from private mind authority in both repository modes.

One projection readiness guard now fences context, retrieval and proposal generation. Central
non-sensory tags live in kernel perception contracts; event finalization never invokes a physical
builder or resolver for operator/director records. Character context remains scoped even when its
operator can inspect raw events or controls a deity body. Existing branch lineage excludes trial
testimony from the same logical body's canonical mind; full campaign revision remains separate work.

Scene and context reads hydrate durable observations into a request-local mind snapshot under
the caller's RLS scope. They never replace the shared projector cache. Accepted embodied command
receipts carry a scoped refresh cursor; the scene API checks the frozen grant's expected
observation before acknowledging readiness. Refresh metadata stays outside character context
and its evidence hash. The console renders only observations and cancels reads on scope changes.

Canonical truth, raw authorization, physical perception, observation, belief evidence, memory,
relationship, and narration are separate records.

`tabletop.character_card_revisions` archives authored content on a saved-card insert or authored
edit. `tabletop.character_bindings` is an append-only controller-configuration ledger that pins a
card revision and exact `CHARACTER` compiled profile to one world/branch/run/body and the existing
mind key. It grants no control and writes no canonical projection. Existing unused legacy persona
entity assignments are not a second binding source. Initial roster assignment creates a missing
binding; adopting another revision requires an explicit successor. Only the pinned self fiction
enters character context, and starting knowledge claims remain distinct from learned evidence.
Live CHARACTER proposal advice uses `domains/tabletop/character_context.py` to resolve that pinned
identity and the shared knowledge boundary. `cognition/character_decisions.py` derives scoped
decision IDs/seeds and runs local utility policy over server-owned movement candidates. Migration
006 stores proposal receipts and existing traces in one transaction, with private forced RLS and
append-only provenance. The durable repository locks the authorized run before the branch and
hydrates a request-local canonical snapshot; reference reads share a command publication lock.
Generation waits for all frozen sensory grants to have corresponding subjective observations.
Advice is PROPOSAL_ONLY, leaves runtime control untouched, and is not an autonomous scheduler.

Explicit handoff is a separate operational path. Migration 007 adds a world/branch/run/body
controller projection and append-only receipts, extending runtime selection with owner/executor
identities, epoch, mode, budget, step, and due time. Body ownership remains unchanged. A dedicated
AGENT receives minimal world capabilities and entity-scoped context grants; it never borrows a
player's session. Ordinary runtime configuration cannot change a managed controller.

The worker reads due rows, resolves pinned context, generates an epoch/step proposal, and submits
through the kernel. Under the mutation lock, controller validation, canonical changes, and step/
budget advancement are atomic. Handoff takes the same branch lock; reference handoff also shares
the direct CommandBus state lock. Missing/stale managed epochs fail closed, including old human
requests. Concurrent workers can commit a logical action only once. Failure pauses and perception
lag defers bounded work. This worker uses local movement utility, not a narrative/world-clock
scheduler. Physical perception grants retain the actual body owner when an executor acts.
Unowned witnesses use authorized world projection infrastructure, leaving the character executor
limited to its own mind. Control records and scheduling metadata never enter sensory fiction.

Durable scene/context requests also hydrate current canonical state into a request-local
snapshot, so actions committed by a separate runner update the existing API's view without
restarting it. This read does not replace the API/projector's shared state caches.

The pure subjective pipeline is:

```text
frozen entity grant -> perceived observation -> belief evidence/revision -> selective memory
             -> goal/need activation -> candidate actions
             -> reflex / utility / bounded plan / typed deliberation
             -> CommandProposal
```

Reflex, utility, and bounded GOAP tiers are deterministic. Model deliberation is optional,
receives an allowed action set, and must return a typed proposal; provider failure falls back to
policy. Runtime assignments cap which tier may act. Relationship changes require a visible
same-branch source event and preserve immutable causal history.

## Population engine

Population operates at three levels:

| Level | Representation | Use |
| --- | --- | --- |
| Statistical | Parquet distributions queried with DuckDB | millions of potential people and cohort analysis |
| Materialized | persistent person and compressed state | households, occupation, finances, beliefs, and scheduled background updates |
| Active | full in-scene cognition state | perception, planning, relationships, and optional model calls |

Pools are immutably bound to a world and branch. Generation streams bounded batches. Filtering,
weighted sampling, stratified sampling, and aggregates execute in DuckDB. Lifecycle transitions
preserve persistent state and monotonic world steps.

## Scenario and evaluation lab

A scenario version specifies a base snapshot, world setup, cohort, intervention, allowed actions,
horizon, stop conditions, runtime/model assignment, seeds, verifiers, and metric contracts.

The lab creates an isolated branch per trial, executes typed proposals, records the trial ledger,
normalizes verifier facts, reduces metrics, and builds a cohort report. Jobs checkpoint per trial,
support cancel/retry, and restore completed inspection history after restart. A process interrupted
while `RUNNING` restores as an explicit retryable failure rather than assuming side effects did or
did not complete.

Calibration compares a synthetic report with versioned evidence. Review approves or rejects the
proposal. Promotion registers an approved immutable version; selecting a runtime version remains
a separate operator decision.

## Storage map

| Store | Data |
| --- | --- |
| PostgreSQL | identity, roles, worlds, branches, projections, actors, entities, sessions, characters, games, minds, lifecycle state, experiment catalogs, telemetry, and ledgers |
| Redis/RQ | experiment queues, job delivery, retry coordination |
| Qdrant | semantic lore and retrieval collections |
| Parquet + DuckDB | large persona pools, cohort queries, population analysis |
| Artifact volume | snapshots, trial outputs, reports, calibration records, replay bundles |
| Static bundle | compiled React application under `static/v2` |

## Package map

```text
TableTop_DM/
├── identity/                 accounts, sessions, roles, audit
├── kernel/                   contracts, command bus, state, branches, API
├── domains/tabletop/         tabletop commands and user portal
├── persona/                  schema, generation, validation, compilation
├── cognition/                subjective state and layered decisions
├── population/               cohorts, Parquet/DuckDB, lifecycle
├── experiments/              scenarios, trials, metrics, reports, calibration
├── frontend/                 React source
├── static/v2/                production frontend bundle
├── infra/                    migrations and Compose
├── scripts/                  lifecycle, tests, readiness, wheel verification
└── tests/                    unit, contract, integration, browser suites
```

The broader workspace concept used to guide the role-specific surfaces is available as the
[multi-surface interface concept](../frontend/design/simulation-kernel-multi-surface-concept.png).

## Non-negotiable invariants

1. Models never own world truth.
2. Human identity, simulation actor, persona, body, mind, and runtime remain distinct.
3. Canonical truth, observation, belief, memory, relationship, and narration remain distinct.
4. Persona profiles and scenario definitions are versioned and reproducible.
5. Every stochastic decision records its seed.
6. Every model decision records model, prompt contract, policy, runtime, and trace provenance.
7. Canonical mutations pass through typed validation and authorization.
8. Experiment branches cannot mutate canonical state.
9. Verifiers emit normalized facts with evidence.
10. Synthetic results are hypotheses, not human ground truth.
11. World-scoped roles and capabilities never leak across worlds.
12. Secrets, credentials, private notes, and secret entity state never enter public projections or
    client-visible logs.

### Embodied population and routines

Optional `life.planning` introduces a finite daily intention menu. `population/planning.py`
selects feasible goals from own bodily needs, configured destinations/priorities and current local
physical conditions; it never reads another body's hidden cognition. Goals commit through the
same world-clock handler, using the existing local movement helper and Activity execution.
Private bounded day/goal counters measure fulfillment, not resources. Actual inventory, health,
fatigue, work and position remain solely on the body. Fixed retry/day/need boundaries preserve
coarse-versus-split behavior. The same routine runs across physical relevance changes, and goal
IDs and choices stay outside sensory projections.

With `life.planning.motivated`, the trusted API composition injects an authorized input reader
(`kernel/api/npc_goals.py`). It builds the NPC's own perception-scoped character context from
event-time grants, requires projected experience to be current, and resolves the exact pinned
CHARACTER profile. Approved deep traits are reconstructed from its immutable blueprint because
durable compiled profile rows omit those fields. No private authored card read is needed by the
clock executor. `cognition/goal_motivation.py` validates each belief against a matching perceived
source claim, caps confidence, and derives bounded motive weights and believed-danger avoidance.
`population/motivation.py` freezes these private inputs under the normal clock lock; the handler
alone commits choices and effects. Missing authority, binding or evidence projection fails closed.
Replay uses committed deltas rather than rereading current minds. This links subjective cognition
to the finite physical goal menu.

The DM character-card association API links an existing canonical body to a saved card without
creating a player account or party seat. Reference locking and durable body-scoped advisory locks
serialize competing associations; durable updates touch association columns only. Persona pins,
mind state, controller assignments, population identity and body resources remain separate.

`population/runtime.py` connects the existing `PopulationLifecycle` to typed canonical commands.
Each embodied member refers to exactly one existing body. Private branch-local member/history
projections hold identity, lifecycle and selected mental metadata; the body's canonical projection
alone owns health, inventory, hunger, fatigue and work output. Binding preserves the independently
pinned character card/persona/mind. Archived source finances are never imported.

Each physical activity stores its own identity, body, start, progress, completion time, and
actual resource inputs and outputs. The due time forecasts completion while work can proceed.
An interruption clears it until work resumes, and a completed activity records its finish time.
Accounting describes changes already applied to the body's resources. When the clock replaces
an activity in the same command, that activity's last accounting record goes into the clock
event with its existing restricted audience. This keeps the physical projections independent
of clock-step partitioning.

An automatic phase switch records its trigger on the new activity and that trigger's cause and
time on the displaced phase. Resuming the previous activity preserves its identity, outputs
and recorded interruption.

Migration 011 adds source binding evidence, scoped foreign keys and freeze guards. The command
transaction locks and hashes the materialized source, commits the binding with projection/event/
outbox, then prevents legacy state or transition writers from changing that source. Reference
execution validates the same source under its command lock. Live API reads overlay the canonical
member rather than treating the frozen source's activation state as current.

`population/routines.py` advances persisted WEED/REST/EAT phases at completion, need and weather
boundaries inside the existing clock transaction. Deterministic phase IDs and a recorded policy
version support replay. Physical proximity determines automatic lifecycle relevance; connection
or camera presence is never an input. Trial copies resolve identity scope from their own branch
and cannot bind another source. Whole-population planning and richer occupations remain separate.

For an enabled routine on a bound NPC, physical relevance also selects when its explicitly
assigned autonomous controller can submit detailed actions. The runner checks its current scene
before policy generation. The command resolver checks it again under the same branch lock used
for the action. Offscreen deferral only changes the controller's next poll time. The clock retains
authority over elapsed routine work, and the NPC retains its identity, controller budget, and
canonical body state.

`population/life.py` adds an opt-in physical schedule to those same routines, under policy
`npc-routines-1.1.0`. A bounded event loop advances all participants to shared movement, need,
sleep, weather and appointment boundaries before choosing their next phases. Travel applies the
same pure cardinal movement/collision helper as manual moves and changes the one canonical position.
It never relocates a body merely to satisfy a meeting. Daily sleep uses simulated time; injury or
accepted human input can wake a sleeper. Captured autonomous actions recheck sleep under the command
transaction, and the character runner preserves its controller budget while the body sleeps.

Social obligations are private branch-local records, not cognition. Attendance requires capable,
awake, physically present participants, and only joint elapsed attendance earns progress. Missing
participants, interrupted attendance and deadlines can cause a missed occurrence. Recurrence stores
counters and the latest outcome rather than creating unlimited jobs. Actual dialogue, beliefs and
relationships still require their existing perception-scoped source events. Scenes expose physical
travel/sleep/social activity but omit plans, destination, route and schedule progress.

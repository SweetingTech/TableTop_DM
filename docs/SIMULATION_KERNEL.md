# Simulation-kernel contract

Clock leases and retry delays are operational metadata outside replay state. The repository
locks pending work under the branch lock and checks its run, executor, epoch, step and lease.
The ledger redacts lease tokens. An idempotent retry returns the original receipt before
checking the current queue.

The outbox ID orders committed events within a branch. Its first unpublished ID is the
projection boundary for that branch. If processing stops after writing some observations,
their exact event/body identities let the retry finish without applying them a second time.
Bounded startup recovery and post-commit projection share this queue with the dedicated worker.
The character proposal path checks the frozen grants against the body's projected observations.
Human input still runs during projection lag. Its physical movement evidence uses the locked
pre-command scene, and evidence that depends on pending observations is omitted.
Delayed writes can use a current world-scoped projector grant when the event-time controller
loses control. The stored observation still uses the event's frozen witness and perception mask.

HTTP private-receipt inspection reads current durable capability through
`sim.has_world_capability(world_id, 'world.read.all')` with transaction-local `app.actor_id`.
This existing RLS primitive checks the exact world and active actor. The API's cached actor model
cannot grant private presentation after another process revokes access. The read changes no
canonical result, seed, cost, receipt or replay state, including for an idempotent cached retry.

Canonical command results retain all quest/offer deltas for persistence, retries and replay.
The HTTP receipt is a separate projection: actors without `world.read.all` in the exact world
receive no private quest/offer delta records. Public result models already exclude source/target
metadata. Presentation filtering is pure and applies equally to original and cached receipts;
it cannot alter committed state, evidence, resource costs or replay hashes.

`tabletop-quests-2.0.0` replaces self-reported counters. Manager-only `quest.configure` validates
same-branch giver/target references and reserves defined gold/items from the giver. Controlled
`quest.accept` pins the owner; MOVE, unique-target DEFEAT, exact-counterparty/item TRADE and
new clock-owned WEED outcomes update evidence only through the authorized handler wrapper.
Objectives combine with AND. Historical work, raw client claims, unrelated bodies, failed actions
and retries cannot increment progress. Source command IDs stay private, while recorded physical
and quest deltas replay together. No later narration or current perception reinterprets evidence.
`quest.claim` requires READY status and current physical giver contact/encounter/readiness;
both participants reserve six seconds and receive normal rest interruption. The reward transfers
only once from reserved funds/items, without minting. Manager `quest.cancel` returns the reserve
once, even after partial work. `quest.advance` now accepts only a quest reference and acknowledges
recorded progress without changing it. Legacy self-reported `tabletop.quests` rows are not evidence
for the new contracts; old committed receipt keys remain readable. Active limits are 256 per
branch, 16 per giver and 16 accepted per body, without a lifetime completion quota.

`tabletop-trade-2.0.0` replaces caller-authored exchange terms with maker-authorized escrowed
offers. Controlled `tabletop.economy.offer` and manager-only `configure_offer` reserve available
items or gold; `trade` accepts `{offer_id, quantity}` with no price, direction or counterparty
override. Both bodies must be capable and adjacent in the same zone/elevation, with a physically
perceived maker and compatible encounter. Acceptance reserves six seconds on both bodies;
passive acceptance does not consume a separate initiative turn. Maker rest is interrupted.
Cancellation and clock handler version 1.5.0 expiry refund remaining escrow once. Active state is
bounded to 256 offers per branch and 16 per maker; consumed/withdrawn offers impose no lifetime quota.
Clockless quotes anchor their bounded lifetime on the first actual clock advance.

`tabletop-action-rules-1.2.0` resolves STR/finesse DEX modifiers and canonical training into melee
bonuses. The typed attack intent still supplies only a target; physical seeds are allocated by
the commit adapter. Manager-only `tabletop.body.configure` accepts bounded definitions without
healing, refilling or replacing inventory. `tabletop.equipment.equip` verifies registered owned
gear and uses the shared controlled-action wrappers, including incapacity, initiative, readiness,
rest interruption and atomic retry. Its sensory summary is in-world and sight-scoped. Canonical
live-sheet abilities/profile are distinct from the immutable authored starting card.

`tabletop-initiative-1.0.0` records start command/run provenance and a stable d20+DEX order in
`tabletop.encounters`. The same branch/run clock selects repeating six-second participant windows.
Clock progression is independent of connection or controller presence. Out-of-turn physical
attempts leave no writes, while per-body action costs still limit movement and resource spending.
Intermediate turn boundaries also constrain offscreen work. Existing active encounters cannot
overlap a body; outsiders cannot bypass the target's encounter through ordinary physical commands.
Historical order and physical seeds stay in the ledger; own-body readiness is the only new
player/cognition scheduling signal. Trials retain the same typed authority and isolated state.

`tabletop.rest.start` is an entity-controlled, intent-only action. It creates an existing Activity
without changing global time or replenishing resources immediately. The clock's isolated working
state applies `tabletop-rest-1.0.0` to both manual REST and NPC REST/SLEEP. Activity recovery metadata
records uninterrupted elapsed time and once-only hourly/eight-hour awards; the body's
`last_long_rest_seconds` enforces 86400 seconds between long-rest benefits. Missing capacities
produce no inferred refill. Independent conditions and death remain authoritative. Exact-boundary,
partition, restart, retry and injected-rollback tests cover the shared transition.

`tabletop.vitals` stores versioned death-save state beside canonical body/clock projections.
Damage-induced defeat records the kernel-allocated physical action seed. Indexed rolls use that
seed and the body identity, so command retries and different clock partitions cannot reroll saves.
New zero-HP damage adds failures; a melee natural 20 adds two. First aid is a typed controlled
contact action; MEND rescues living zero-HP bodies. No ordinary action clears a dead flag.
Clock expiry/recovery and physical bodies publish atomically; snapshots and recorded replay
already retain these ordinary projections. Clockless pending saves start on the first clock advance.
Pre-existing zero-HP bodies without a source record are not assigned invented old saves.

Saves occur every six seconds: 10+ succeeds, natural 1 counts two failures, natural 20 restores
1 HP. Three successes stabilize; three failures kill. Stable bodies with known positive maximum
HP recover 1 HP after one simulated hour. Permanent conditions are independent of this recovery.
Resolver 1.4.0 denies new sight/sound grants to dead or unconscious/zero-HP observers, frozen
at event time. Existing memories/grants remain historical; private save records never enter the
character scene/context. Terminal recovered records retain their final rolls for operator audit
and do not run again on later ticks. Own-body human introspection remains available. Rest and initiative
still require the remaining original C3 work.

`tabletop.entity.set_controllers` requires world-scoped `entity.control`, `mind.write.all` and
canonical commit authority. Its typed metadata changes, sensory-controller projection, fenced
runtime state, ledger and outbox share one commit. The command emits no sensory evidence.
It can finalize a roster seat inside an explicit same-actor database unit; in-process publication
waits for the outer commit. Nested failures make the unit rollback-only and cannot switch actors
or databases. Reference seat publication participates before state/receipt publication.

`tabletop.map.configure` changes presentation only, with world-scoped entity-control and broad
world-read authority plus branch commit/proposal checks. It emits no sensory evidence and does
not move bodies, create physics zones or alter visibility. Maps remain branch-scoped and trial
changes remain isolated. Interface metadata is filtered after ordinary scene authorization;
models continue receiving the original cognition contract.

Durable experience readiness preserves immutable observation IDs created at six-decimal precision
when persisted grants/observations have four-decimal confidence. Compatibility requires the same
source event, body, complete frozen payload mask, event time and equivalent stored confidence.
Reference mode retains strict ID checks. No audience is recomputed and no evidence is rewritten;
existing observation validation still clamps confidence to the frozen grant.

The controlled-command action-time wrapper reads the branch clock and body's last readiness,
then appends a SET delta in `tabletop.action_time` only after an accepted handler result. Effects,
resource spending, wakeup, readiness, event and outbox persist atomically through both adapters.
Actions never advance the clock. A retry returns its original receipt before current readiness
checks; new distinct commands racing for one body serialize under the branch lock. Waiting raises
`BodyActionPending`, an expected runner suspension that consumes no step or failure budget.
Integer-second duration is six for physical actions and ceil(30/speed) with a
minimum of one for a five-foot move; zero-speed movement is rejected. Guard expiry is applied in
the clock's isolated working copy and emitted as ordinary body deltas. No-clock branches preserve
untimed behavior; clock-run mismatch rejects new actions. Speech, console interpretation and quest
bookkeeping reserve no physical time. Physical command versions record
`+voluntary-body.2.action-time.1`; camera modes use `+presentation.1`, clock tick/advance use1.2.0,
divine blessings use1.1.0, action rules use1.1.0, and the action catalog uses1.4.0.

`tabletop.condition.apply` requires world-scoped `entity.control` and `action.propose`, an existing
body in the branch and a clock belonging to the same run. Its strict request selects one of six
registered conditions and duration1..86400 seconds, never an expiry or canonical delta. At most
32 independent timed sources can be active on a body; duplicate receipts remain readable at
capacity and after expiry. Timed records are distinct from permanent conditions, so removing one
source cannot erase another. These operator configuration events do not create sensory evidence.
The body's own allowlisted live state can still report its current physical conditions.

Clock advancement anchors legacy blessings at the prior clock time, then advances through all
due weather/effect/readiness boundaries. It accrues blocked intervals without voluntary work,
expires due sources and reconciles zero elapsed time at the boundary. Existing positive-health
requirements remain for activities and attendance; a missing HP field cannot fabricate work.
All intermediate changes remain private until the complete typed clock result commits atomically.
Historic deltas and receipts are not rewritten.

The portal rejects bound-card resource/world edits before any metadata/history save, including
mixed requests containing permitted identity changes. This is not a second physical mutation
handler: live changes still require typed authorized kernel commands. Initial unbound-card stats
remain authored setup; editing a bound card's identity does not heal, equip or relocate its body.

The character live-state endpoint is read-only. Its pure projection accepts only a matching
canonical world/body, exposes an allowlist of physical resource fields and never copies arbitrary
public-state keys, entity secrets or card backstory. No command, ledger event, outbox record or
portal resource synchronization is produced. An unbound card is explicit AUTHORED; a missing bound
body is unavailable rather than a stale-card fallback. Kernel commands continue owning live effects.

The registered voluntary-action wrapper rejects zero-HP, defeated, dead, stunned, unconscious
and paralyzed bodies. Ordinary sleep is distinct: captured CHARACTER_POLICY actions suspend
without a control step; a human action may wake only if its handler succeeds. The handler sees
an isolated awake evaluation view, and an appended delta commits wakeup atomically with effects.
Legacy bodies lacking an HP field remain eligible for non-combat voluntary actions; combat/spells
still require explicit positive actor HP. Dead markers remain authoritative even with stale positive HP;
ordinary healing does not clear them. New damage-induced defeats follow the death-save rules above;
ordinary healing can rescue a living target at zero HP but cannot resurrect a dead one.
`BodyIncapacitated` is expected runner suspension, including a condition acquired during model
generation before commit. Waiting does not spend controller steps/failures or disable autonomy.

`cognition/decide` CHARACTER mode is proposal-only and shares the entity-scoped trusted builder,
authorization, projection barrier and receipt identity. It cannot accept caller situations, actions,
personas, seeds or planner/provider overrides. Its authenticated actor remains subject to exact
world/branch/run/body authority. Legacy EVALUATION mode retains privileged caller-authored input
for SIMULATED_PLAYTESTER personas; it does not provide live character knowledge.

Random mechanics declare `uses_randomness` in their command definition. Both commit adapters
derive a 63-bit action seed from the RNG policy version, recorded run seed, next committed branch
sequence and command type. Failed commands publish no sequence advancement; concurrent commands
serialize; receipt retries allocate nothing. Non-random commands also advance the branch sequence.
Legacy null run seeds resolve to zero, which is recorded in each proof; new omitted run seeds are
stored as zero. Actor/run UUIDs and caller text/seeds do not influence mechanics RNG. Independent
runs with equal seeds and command order intentionally share random numbers for comparisons.
The handler receives the action seed; the original proposal/event seed retains policy provenance.
The private canonical result stores the typed proof; frozen physical observations do not include it.
Standalone canonical buses require a trusted run-seed reader. Only isolated low-level trial harnesses
may explicitly inject handler seeds; application-backed trials use the same allocator as live play.

TableTop DM is one domain-neutral simulation system with three execution modes:

```text
                         Simulation kernel
                                |
              +-----------------+-----------------+
              |                 |                 |
          Live world        Population        Evaluation
          persistence       distributions     snapshot branches
          active minds      cohorts           simulated players
          tabletop play     background state  normalized facts
```

Tabletop is the first domain pack, not the definition of the kernel. Persona, cognition,
population, and experiment packages do not own canonical tabletop state. Every domain action
enters the same validated command boundary.

## Conceptual provenance and independence boundary

[MatrAIx](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B) is credited as a source of conceptual
inspiration for several evaluation methods: constrained persona definitions, seeded and stratified
sampling, reproducible trials, task-specific verifiers, normalized trial output, and cohort-level
aggregation. TableTop DM reimplements the useful general ideas in its own architecture; it does not
integrate the MatrAIx application.

The boundary is explicit:

- no MatrAIx source code or runtime imports;
- no MatrAIx package, Git submodule, service, model, dataset, or schema dependency;
- no Harbor stack, MatrAIx frontend, or MatrAIx deployment component;
- no requirement to install or run MatrAIx;
- no claim that synthetic cohorts replace evidence from real people.

MatrAIx is primarily simulated-user evaluation infrastructure. TableTop DM is a persistent,
deterministic world kernel with tabletop, cognition, population, spatial-perception, and isolated
scenario domains. The attribution explains where some evaluation concepts came from without
implying shared code, shared runtime, or repository coupling.

## Required object separation

- A **user account** is a human login with profile data and global/world role grants.
- An **actor** is the world-scoped authority that proposes or observes simulation activity.
- A **PersonaBlueprint** is a versioned identity with dimensions, derived traits, provenance,
  and validation.
- An **EmbodiedEntity** is branch-scoped physical state such as location, health, inventory, and
  controller.
- A **MindState** holds an entity's mutable observations, beliefs, memories, relationships, and
  decision history.
- An **AgentRuntime** is the deterministic policy, planner, model provider, replay fixture, or
  human operator currently producing proposals.

Changing a runtime does not change the persona. An event becoming canonical does not make every
observer know it. Narration does not become state. A platform role does not implicitly grant
authority in every world.

Persona purpose separates an in-world `CHARACTER` from a `SIMULATED_PLAYTESTER`. A character's
compiled identity and trait prompts exclude tabletop/interface preferences and player onboarding
or GM relationships. Purpose is persistent and versioned; switching execution runtime never
changes it. This filter does not authorize arbitrary situation text or establish which lore a
character knows; trusted live context and knowledge-scoped retrieval remain separate boundaries.

Read-only character-context assembly now validates stored experience against the same branch's
source events and frozen physical grants. It cannot promote operator summaries into sensory
facts. The model-facing situation excludes ledger/controller/timeline metadata. Caller-authored
decision requests are restricted to privileged playtester evaluation; character requests fail
closed to caller-authored live situations; trusted proposals resolve pinned authored identity and
the server-owned movement catalog before deciding.

## Constitutional order

Character proposal generation is an operational read/decision path, never canonical mutation.
It accepts no client-authored fiction or candidate actions, resolves an exact CHARACTER binding,
requires actual body control and scoped command capabilities, and waits for dependent perception
projection. Immutable receipts/decision traces preserve server seeds and policy/context/catalog/
compiler/persona provenance. Retry keys are scoped by world/branch/run/body/actor.
Only normal command submission can apply the proposed action, after current kernel validation.
Proposal receipts are not execution leases and must never substitute for future controller epochs.
Policy advice is labeled CHARACTER_POLICY and cannot become human behavior ground truth.

Managed execution requires the current controller epoch and authority. HUMAN ownership and the
autonomous AGENT executor remain distinct. Autonomous proposals carry CHARACTER_POLICY authorship,
epoch, and expected step. The kernel validates inside the mutation lock, before the handler; one
transaction commits action/event/outbox and advances step/budget. Private handoff takes the same
lock and increments the epoch, fencing in-flight work. The API never upgrades old managed commands
by stamping a new epoch. No handoff is sensory. These controls apply to canonical LIVE runs;
complete campaign checkpoint/timeline restoration must eventually restore and fence them too.

1. A human, policy, planner, or model creates a typed `CommandProposal`.
2. The registry resolves a stable command contract and validates parameters.
3. The kernel checks actor identity, world/run/branch lineage, capabilities, entity control, and
   branch eligibility.
4. A deterministic handler returns a result and explicit state deltas.
5. Deltas commit atomically to one branch projection.
6. The command, result, resulting state hash, event, and outbox record are appended.
7. Observation, belief, memory, relationship, metrics, or narration may be derived afterward.

A rejected proposal leaves no partial state. Retrying the same actor/run/idempotency tuple
returns the original committed receipt.

## Acceptance properties

Typed world-clock configuration, advance and ticks mutate the existing branch projection. A tick
rechecks executor/epoch/step and LIVE run status in the command transaction. Scheduled weather,
activity progress, body outputs, next clock step, command/event/outbox either all commit or all
roll back. Exact retries return the original receipt after pause; new stale work is rejected.
Configured clock pause also fences unattended character proposals inside the mutation lock.
No arbitrary queued model command executes, and no viewer is required for offscreen progression.

Optional dialogue generation proposes text only after policy action selection. Bounded network
and schema failures use deterministic fallback. Accepted text/model/prompt/source metadata freeze
in the existing private receipt before submission. Retries reuse that receipt. Speech carries
empty claims and cannot apply another action or world delta. No provider is active by default.

Guard consumes its defensive benefit once. Melee resolves registered owned equipment, body
bonuses, poison/fear disadvantage, reach, current sight/zone and incapacity inside the mutation
transaction. Both spell aliases resolve learned registered definitions and recheck mana,
range, sight, zone and eligible living targets; rejection consumes no mana or health. Rule version
is recorded privately with the canonical result, outside physical perception masks. A retry reads
its original scoped receipt before current schema normalization, preserving committed old-contract
requests. Migration 010 retains human choice source/origin/RLS rules; these stricter rules require
no additional migration. Logical action seed allocation and full combat time/lifecycle remain open.

Speech/combat training records only accepted untraced human actions whose selected action existed
in the locked pre-command perceived catalog. Operator, stand-in and submitted-policy actions are
excluded. Attack evidence has physical event-time perception grants. Hidden or unprovoked bodies
are not autonomous melee targets; no candidate reads hidden armor, hit probability or health.
Basic attack parameters come from the server contract, never copied damage modifiers from history.
Context `character-context-1.2.0` orders known observations by canonical event sequence; provenance
remains private even when timestamps tie. Existing movement-profile versions remain readable.

Private human movement evidence commits atomically with its accepted source command, event and
outbox. Retries add neither another action nor another sample. Its input-origin field is independent
of controller authority; traced advice, autonomous executors, automation, rejected commands and
legacy unknown-origin records are excluded from human preference learning. Behavior provenance,
confidence and contradictions remain outside sensory payloads and model-facing situation text.
Profile reconstruction uses only the exact current world/branch/run/body/player/character. Complete
rewind of this evidence alongside all campaign state remains part of timeline revision work.

- Schema version + seed + fixed dimensions always produces the same valid persona.
- The same persona, policy, state, seed, and runtime assignment produces the same deterministic
  decision trace.
- Two observers may derive different beliefs from the same canonical event.
- Relationship changes retain immutable before/after vectors and a visible same-branch source
  event.
- Population cohorts are checked for feasibility and declared distribution tolerance.
- Population lifecycle transitions remain bound to their original world and branch after
  restart.
- Trial branches originate from immutable snapshots and cannot write canonical projections.
- Snapshot 2.1 freezes entity metadata alongside one projection boundary. Nested restoration uses
  that frozen source, and metadata changes alter snapshot identity without altering replay hashes.
- Controlled relationship changes derive their classification from the source entity's frozen
  physical mask. Raw event access alone does not establish a perceived promise, rescue or insult.
- Learned-lore retrieval and conversation use the same validated body/branch evidence and pinned
  starting claims. Global public lore, operator knowledge and broad scene authority confer no
  character memory. Recollections stay subjective; they do not alter canonical truth.
- Event finalization suppresses physical emission and audience resolution for non-sensory
  operator/director/evaluation/checkpoint records, regardless of a supplied emission builder.
- Generic scenario jobs retain checkpoints, trial event envelopes, verifier facts, normalized
  metrics, and reports after restart.
- Calibration review and deployment promotion are separate actions.
- Public entity projections never expose secret state.
- Tactical, third-person, and first-person controls operate on the same commander, squad, weapon,
  health, enemy, and branch state; renderer frames remain perception-scoped.
- Synthetic outputs remain labeled hypotheses rather than evidence about real people.

## Supporting documentation

Character identity bindings are versioned controller configuration, like runtime assignments;
they do not mutate world truth, grant body control, or enter the sensory ledger. A binding pins
immutable authored content and a `CHARACTER` compiled profile to exact world/run/branch/entity
lineage and an existing mind. Rebinding preserves subjective history and runtime selection.
Authored starting claims stay outside canonical facts and learned evidence. Future autonomous
execution must resolve this binding and still submit authorized typed kernel proposals.

An accepted command's scene-refresh cursor is operational metadata, outside the character's
situation and evidence hash. Checking readiness reads the original event-time perception grant
and subjective projection; it does not resubmit the command, mutate a mind, recompute an audience
from current location, or expose canonical payloads. An unperceived action needs no fabricated
experience. Durable scene/context hydration is request-local and leaves projector caches intact.

- [Architecture and invariants](ARCHITECTURE.md)
- [Network and deployment diagram](NETWORK_AND_DEPLOYMENT.md)
- [Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md)
- [API and user workflows](API_AND_WORKFLOWS.md)
- [Operations](OPERATIONS.md)
- [Testing](TESTING.md)

The visual product direction is captured in
[the simulation-kernel concept](design/simulation-kernel-concept.png). The running React client
and typed API contracts are authoritative for interaction behavior.

## Population binding and continuous routines

Activity timing and resource accounting are canonical clock outputs. A runnable activity's
`due_seconds` is its expected completion given uninterrupted progress. A waiting or cancelled
activity has a null due time, and a completed activity retains its actual completion second.
The kernel records food consumed, work produced, and recovery as cumulative per-activity
amounts. Body projections remain authoritative for balances. When a clock command replaces a
phase, its accounting goes into the same committed clock event. Replay consumes the recorded
deltas and never grants an output a second time.

Daily planning uses the existing typed routine configuration and fenced clock command. Its
bounded intention menu and private `planner` metadata are not additional authority. Actual goal
time, route steps, needs, daily resets, choices and canonical effects commit atomically with the
receipt; exact retries cannot fulfill an intention twice. No network/model callback runs under
the clock lock. Goal selection reads own physical needs and approved local destinations, never
arbitrary private mental state. Optional motivation reads only the bound body's authorized,
event-grounded subjective context and pinned CHARACTER traits. Its typed, scope-checked input
records the policy/compiler/persona versions, deterministic seed, semantic input hash and source
evidence IDs privately with the routine projection. The wrapper refreshes these inputs under the
same command lock before execution, and the normal transaction commits them with effects, receipt,
event and outbox. Failure rolls everything back; exact retry and replay retain the original inputs.
Current private DM notes, secret state, unsourced beliefs and unheard claims are not policy inputs.
Priority/distance/ID ordering, fixed retry boundaries and preserved
partial phases make outcome independent of tick partitioning and human viewers. Midnight resets
daily fulfillment only; it cannot refill inventory or erase body fatigue/health/work.

`tabletop.population.bind` is a canonical-only command. Its internal binding instruction is excluded
from public result JSON. Durable execution locks and verifies the source version/content hash in
the same transaction as its projection, command, event and outbox. Migration 011 freezes that
source after binding and rejects stale legacy transition inserts. Generic consequence promotion
cannot create, remove or rebind population identities; live lifecycle changes may still be promoted
from trials. The source member parameter is redacted from the command log. Reference validation
runs before publishing under the command lock.

`tabletop.population.level` and `tabletop.routine.configure` support canonical and isolated trial
branches with normal world capabilities and version checks. Bound member/history projections omit
stored world/branch IDs and resolve them from the current branch when restored. The canonical
body is the single physical resource owner; lifecycle changes preserve work and never copy balances.

Clock advancement updates routine phase, activities, needs, food consumption, work output and
relevance transitions atomically. The initial policy is `npc-routines-1.0.0`; stable phase IDs and
ordered completion/need/weather boundaries produce identical results for coarse and split advances.
Food is spent once when a meal completes. Zero food, rain, displacement and incapacity wait without
awarding unavailable work. Routine ownership excludes simultaneous manual activity ownership.
Reconfiguration is an explicit replacement; disabling cancels managed work. There is no new worker
or wall-clock progression path outside the existing fenced world clock.

The opt-in life plan extends this policy to `npc-routines-1.1.0`. Shared physical event boundaries
cover travel steps/arrival, daily sleep/wake, hunger/fatigue and social deadlines/completion.
Each clock command atomically commits positions, needs, suspended work, routine phase, obligation
progress and relevance. Retrying a clock receipt cannot move a body, spend food or award attendance
again. Travel uses the manual movement helper, a stable bounded A* route and current collision checks.
Relevance is reconciled at actual movement boundaries even within coarse clock advances.
The character runner and shared command resolver use that same physical rule for enabled,
population-bound NPC routines. Detailed autonomous actions require current `ACTIVE` relevance.
The resolver checks the current branch before executing a new action. An offscreen body follows
its persisted routine while the controller defers its next poll without spending a step or adding
a failure. An authorized idempotency retry resolves its original committed receipt.

`tabletop.obligation.schedule` and `.cancel` use normal world management capabilities and lineage
validation on both canonical and trial branches. Cancellation checks occurrence. Plans and obligation
records remain private; they do not grant character knowledge or fabricate dialogue/relationships.
Sleeping is canonical bodily state. Action handlers recheck it at execution: a stale character policy
is suspended with `BodySleeping`, while an accepted human action wakes its own controlled body in the
same receipt. Sleep does not change actor/persona/card identity or controller epoch/step.

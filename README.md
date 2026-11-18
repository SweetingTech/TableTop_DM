# TableTop DM

![A coastal village comes to life from a tabletop map as a party crosses a bridge and a gardener keeps working.](docs/images/tabletop-dm-banner.png)

TableTop DM is a local-first tabletop platform with a persistent world that can keep moving
between sessions. Host a game with friends or play with characters whose autonomous choices draw
on their card, backstory, and observed play history.

[Quick start](#quick-start) · [Role setup](docs/ROLE_SETUP_GUIDE.md) ·
[Campaign roadmap](docs/AUTONOMOUS_CAMPAIGN_CHECKLIST.md) · [Documentation](#documentation)

## What works today

- Hosted games support world-scoped roles, character binding, and a live perception-scoped console.
- Explicit character handoff lets a configured runner act while a player is away. Optional
  dialogue generation uses an endpoint and model chosen by the operator.
- The world clock advances work, meals, rest, commutes, and appointments while the party is
  elsewhere. Changes in weather, danger, or bodily needs can interrupt and resume that activity.
- Commands, snapshots, replay, and isolated trials retain a history the DM can inspect. The
  campaign roadmap tracks complete rewind, authored story direction, and an executable AI DM.

## Implementation details

The durable world runner claims the next clock step in PostgreSQL. Another worker can recover
the step if the lease expires before commit. Pausing cancels pending work, and a successful tick
records its result and schedules the next step together. Apply migration 014 before upgrading.

Durable receipt inspection checks the current database grant, including when another API process
changes an actor's roles. A long-lived API's cached DM grant cannot preserve private access.

Ordinary command receipts omit internal quest/offer projection deltas. The canonical receipt
and replay evidence remain complete; inspecting them requires read-all authority in that world.

Quests use manager-authored movement, defeat, trade or weeding objectives and rewards reserved
from the giver's actual goods/gold. Inspect a nearby giver, accept an offer, then complete its
objectives through ordinary actions. The personal journal follows committed outcomes, including
offscreen work. Return to a capable nearby giver to claim the promised reward once. Console
commands are `/quest accept|status|claim <quest id>`. Requests cannot supply progress or reward
amounts. The autonomous planner's pursuit of these opportunities remains a later checklist item.

Trade uses standing offers backed by the maker's carried goods or gold. In the console, inspect
an adjacent merchant and choose an offer to prepare a command, then send it. `/offer buy|sell
<item> <quantity> <unit price>` posts your own offer; `/trade <offer id> [quantity]` accepts its
fixed terms and `/withdraw <offer id>` returns your reserved resources. Both participants must
be capable, visible and adjacent; an exchange occupies both bodies for six simulated seconds.
Expired or cancelled offers return the unused reserve once. Whole-section verification and
independent acceptance remain separate from individual trade/quest implementation changes.

Attacks use canonical ability scores, weapon rules and training. Shortswords may use the higher
of Strength/Dexterity; unarmed attacks and spears use Strength. `/equip UNARMED|SHORTSWORD|SPEAR`
readies an owned weapon and spends the normal action cost. The live sheet follows current body
scores and attack/damage bonuses, while the authored character card remains separate.

New defeats start death saves every six simulated seconds: three successes stabilize, three
failures kill; a natural 1 counts twice and a natural 20 restores 1 HP. Saves use recorded
kernel-owned damage seeds. Healing can rescue a living body at 0 HP, and `/stabilize <target>`
provides adjacent first aid with a six-second action cost. Stable bodies recover 1 HP after
one simulated hour. Ordinary healing cannot resurrect the dead. Old zero-HP bodies are not
retroactively given a defeat history. `/rest short` takes one simulated hour and restores a
quarter of known maximum HP, rounded up. `/rest long` takes eight hours and also restores HP
and mana to known body-owned caps, at most once per 24 simulated hours. Physical effort or damage
interrupts rest. Offscreen NPC rest and sleep use the same recovery rules. World managers can
start an encounter with kernel-rolled initiative: six-second action windows rotate on the same
world clock, so absent participants never freeze offscreen life. These versioned continuous-time
rules retain ordinary per-body movement/action costs; they are not every tabletop ruleset.

Roster assignments prepare an uncontrolled body and pinned character binding before publishing
the seat and human control together. Failed preparation can be retried. Removing the last seat
keeps the physical character and its history, revokes human control and pauses its runner; it
does not revoke the account's world role. Apply migration 013 before starting this version.

With a world clock configured, each successful controlled physical action reserves that body's next
available simulated time. Combat, spells and other physical actions take six seconds. Speech and
quest bookkeeping do not reserve physical action time. Camera changes are presentation only and
neither wait for readiness nor wake the body. A five-foot grid step uses the body's speed
and rounds up to whole seconds (one second
at speed30, two at speed15). Retries reuse their original cost and receipt. Autonomous characters
wait without losing control budgets, while the world keeps moving. Guards expire after six
simulated seconds. Worlds without a clock retain their existing untimed behavior.

World managers can apply bounded timed conditions through `tabletop.condition.apply`. Timed
conditions stack independently from permanent conditions. Clock advances process expiry,
readiness and weather in time order, so incapacitated or busy people do not accrue offscreen
work or social attendance during blocked intervals. Living needs continue. Divine blessings
expire after six simulated seconds per requested turn; old remaining-turn grants start their
countdown on the first new clock advance.

Language models may propose dialogue or actions, but they never write canonical state. Typed
commands, world-scoped authorization, deterministic handlers, atomic transactions, and an
append-only ledger decide what actually happened.

Controlled relationship reactions now derive from frozen physical evidence: heard speech can
increase familiarity, and a perceived damaging attack can change trust and fear. Callers cannot
label unrelated events as promises kept or lives saved. New snapshots freeze entity identity,
controller and private metadata for nested trials. Apply migration 012 before running this
version; these snapshots remain foundations for complete campaign rewind, not whole-mind checkpoints.
See [snapshots and trials](docs/API_AND_WORKFLOWS.md#snapshots-and-trials).

Character knowledge retrieval uses learned testimony and pinned starting claims rather than the
world's public lore catalog. Older learned facts remain searchable after recent conversation
scrolls out of view. Operator directions cannot emit sensory evidence, and broad scene inspection
does not grant access to another body's memories. Generated replies use the same scoped sources.
See [character knowledge](docs/API_AND_WORKFLOWS.md#character-knowledge).

`POST /api/v2/cognition/decide` accepts an explicit `mode: "CHARACTER"` request with world,
branch, run, embodied entity and idempotency key. It uses the trusted pinned context/proposal
path, returns a proposal without committing, and rejects caller-authored context or action lists.
Legacy caller-authored evaluation remains restricted to privileged playtester flows.

Owners can read a character's canonical body at
`GET /api/v2/player/characters/<character_id>/live-state`. It returns current HP, status, mana,
inventory and equipment with the canonical branch/version, separately from the authored card.
Unbound cards report an authored source; missing or unauthorized bound bodies do not fall back
to old card values. Once a card has a body, card edits cannot change its HP, status, max HP,
armor or speed, or retarget its world. Use authorized world actions for live changes. Identity
editing and unbound-card setup remain available. The Player Dashboard shows live health, status,
mana, inventory, equipment, learned spells and conditions. It refreshes the selected sheet every
five seconds while visible, with a manual Refresh control. Loading and failed reads never show
old card resources as live state. Polling preserves unsaved character identity edits.

Melee proposals choose a target; the kernel resolves owned equipment, ability/training bonuses, reach,
visibility and conditions. Both spell entry points use registered ARCANE_BOLT/MEND definitions
and the body's learned spells. Cast/invoke share fixed power, cost and eligibility. New requests
cannot supply dice, bonuses, spell power or mana cost. The matching console accepts
`/cast MEND <target>` and `/invoke MEND <target>`. Merge and deploy this console/bundle change
together with its backend contract update.
Melee rolls use a recorded run seed and the next committed branch sequence. New identical
attacks get independent seeds; retries return the original receipt. Configured clocks enforce action
readiness, initiative windows, timed conditions, death saves and recovery as described above.

Voluntary actions share incapacity checks. A human-controlled sleeper can wake by a valid
action, including combat or magic; failed attempts leave sleep and resources unchanged. Sleeping
stand-ins wait for wakeup. Ordinary healing cannot resurrect a body marked dead.

Bound characters can now produce persisted, retry-safe action proposals from their pinned identity
and perception-scoped experience. The proposal endpoint uses local deterministic policy and the
perception-scoped movement, speech and tactical catalog. The proposal endpoint itself
does not execute actions, change a human assignment, or run a campaign.
See [character proposals](docs/API_AND_WORKFLOWS.md#trusted-character-proposals).

The console refreshes authorized scenes every 2.5 seconds while visible and resynchronizes on
reconnect or focus. It ignores obsolete/older responses, preserves drafts during background
refresh, and clears local state when choosing another character. Interrupted reads are marked
stale; actions wait for synchronization and projected experience. Unavailable live reads never
become demo scenes. Maps use per-zone configuration and every perceived positioned entity.
Unconfigured/out-of-bounds views use a coordinate grid instead of a fixed Harborport map.

The Game Console now offers **Let character act**, **Pause autonomy**, and **Take control**.
Explicit handoff starts a bounded local character policy through a dedicated executor;
the runner and perception projector continue without a browser connection. Controller epochs
prevent old human or autonomous actions committing after takeover. This is basic unattended
movement, contextual speech and responses to perceived attacks. Comparable human choices guide
direction, reply intent/volume, attack, withdrawal and visible-target priorities, with pinned
persona/card tendencies as fallback. A one-attack guard and fixed-cost ARCANE_BOLT/MEND spells
expand combat when resources allow. An optional OpenAI-compatible adapter turns speech intents
into contextual generated utterances; you choose its endpoint, model and credentials. Generation
is off by default. Full tactical planning, relationship strategy and narrative goals remain planned.
See [controller handoff and runner](docs/API_AND_WORKFLOWS.md#controller-handoff-and-runner).

See [generated dialogue and tactical choices](docs/API_AND_WORKFLOWS.md#generated-dialogue-and-tactical-choices)
for activation, exact combat rules and current limits. No provider is silently selected or activated.

An opt-in persistent world clock now advances offscreen weeding and rest alongside character
actions, without a browser or nearby observer. Scheduled rain interrupts work at simulated-time
boundaries; returning players see inspected activity/progress in the console. A separate
`world-runner` uses an explicitly granted agent, epoch/step fencing and the normal atomic kernel
transaction. Configure pause, speed, stop boundary and downtime policy through typed commands;
see [world time and offscreen activities](docs/API_AND_WORKFLOWS.md#world-time-and-offscreen-activities).
Population binding, finite meals, daily sleep, local travel and recurring appointments now share
that clock. A routine-bound NPC with a pinned character and an autonomous controller adds
detailed character actions while physically relevant. Its background work continues between
encounters, and it keeps the same controller and unfinished tasks when the party returns.
Activities retain their next completion time while runnable and record actual resources consumed
or produced. When a clock step replaces an activity, its accounting remains in the clock event.
When a need or scheduled commitment pauses work, the activity retains why it paused after
it resumes.
Optional [daily planning](docs/API_AND_WORKFLOWS.md#daily-goal-planning) lets NPCs choose
among prioritized work/rest goals with daily limits, seek shelter, recover from displacement or
injury, and resume unfinished goals. No viewer or additional model provider is required.
Optional [belief/persona motivation](docs/API_AND_WORKFLOWS.md#belief-and-persona-driven-npc-goals)
lets bound NPCs weight duty, curiosity, care and recovery differently, reconsider goals after
perceived claims, and avoid places they believe dangerous. Only their own validated observations
and pinned CHARACTER persona inform those choices. The initial goal vocabulary remains work/rest.

## Product workspaces

| Workspace | Audience | Purpose |
| --- | --- | --- |
| Game Console | signed-in users | View a world, inspect visible events, and submit dialogue or typed tabletop actions |
| Player Dashboard | Player | Create, generate, import, inspect, and manage saved characters |
| Dungeon Master | DM | Create and host games, manage rosters, schedule sessions, and maintain public/private notes |
| Admin Dashboard | Administrator | Create, edit, disable, or delete accounts; reset passwords; assign global and world roles; inspect audit history |
| Control Plane | Administrator | Create worlds, actors, entities, runs, snapshots, and isolated branches |
| Persona Studio | Administrator | Generate, validate, version, compile, and inspect persona blueprints |
| Population Studio | Administrator | Generate population pools, define cohorts, sample strata, and manage activation lifecycles |
| Scenario Lab | Administrator | Run reproducible experiments against immutable world snapshots |
| Run Inspector | Administrator | Inspect jobs, trials, ledgers, metrics, decision traces, and replay state |
| Calibration | Administrator | Compare synthetic metrics with evidence, review proposals, and promote approved versions |
| Settings | every account | Manage profile, password, locale, timezone, pronouns, and session state |

DM roster controls explicitly choose Player or Co-DM and can assign a player's saved character
when inviting them or updating an existing membership. Assigned player characters receive an
embodied viewpoint in the Game Console.

After an accepted action, the Game Console reloads that character's perceived scene and waits
up to eight seconds for the corresponding observation. Its feed renders observations once per
source event. A failed refresh preserves the accepted status and retries reads without resending
the action; switching worlds or viewpoints clears local drafts and ignores old responses.

Character cards support a validated backstory, motives, values, bonds, character secrets, and
starting knowledge claims in creation, JSON import, and editing. A deterministic `card_version`
identifies the current authored content. These claims do not grant canonical knowledge or activate
a stand-in. Authored edits now retain private immutable revisions. Assigning a saved character
to a game creates an initial binding that pins its card revision and `CHARACTER` persona to the
world, branch, run, body, and existing mind. Later edits do not silently change that binding;
an explicit successor binding adopts a selected revision without resetting experience or control.
The initial persona uses a deterministic card-seeded baseline with the authored fiction supplied
separately in character context. Accepted human movement now supplies separate private behavior
evidence without changing that persona, card, mind, or control ownership.

Persona APIs distinguish `CHARACTER` from `SIMULATED_PLAYTESTER`. Character compilation uses
in-world core/world traits and omits player controls, onboarding goals, GM relationships, and
interface preferences. Existing evaluation personas retain their playtester behavior. This is the
first knowledge-separation foundation; autonomous character context and unattended campaigns are
still tracked in the [implementation checklist](docs/AUTONOMOUS_CAMPAIGN_CHECKLIST.md).

Embodied context reads now share the perceived-scene service and validate remembered evidence
against same-branch frozen perception grants. Caller-authored cognition requests are privileged
playtester evaluation. Context reads now supply a versioned basic movement-attempt catalog for
controlled, capable bodies, using perceived self state and world-scoped authority. Hidden obstacles
do not filter choices; the kernel checks every attempt. Trusted character proposals and explicit
controller handoff now enable bounded unattended movement through the runner. Caller-authored
evaluation remains separate from live character inputs. Broader actions, narrative planning, and
broader player-history imitation remain in the implementation checklist. See
[movement behavior profiles](docs/API_AND_WORKFLOWS.md#movement-behavior-profiles).

The initial account is `admin` with password `admin123`. The first sign-in is restricted to the
password-change screen, and the replacement password must be at least 12 characters and not a
common default.

## System layers

| Package | Responsibility |
| --- | --- |
| `identity/` | Accounts, secure password hashing, sessions, profile data, audit records, and global/world role grants |
| `kernel/` | Actors, capabilities, typed commands, state transactions, events, visibility, snapshots, branches, replay, and API composition |
| `domains/tabletop/` | Characters, games, sessions, battlefield control modes, squads, unified weapons, dialogue, movement, combat, magic, economy, factions, divine effects, quests, and content rules |
| `persona/` | 80 versioned dimensions, dependency-aware generation, constraints, validation, provenance, compilation, and prompt budgets |
| `cognition/` | Perception, observations, beliefs, memory, relationship vectors, reflexes, utility policy, planning, and typed deliberation |
| `population/` | Parquet persona pools, DuckDB filtering/sampling, cohort feasibility, materialization, activation, and compression |
| `experiments/` | Immutable scenarios, trials, jobs, verifier facts, metrics, reports, comparisons, calibration, and consented telemetry |
| `frontend/` | React single-page application and role-aware workspaces |
| `infra/` | PostgreSQL migrations and the Docker Compose deployment |

The canonical mutation path is:

```text
proposal -> typed validation -> actor/capability/entity-control checks
         -> deterministic domain handler -> atomic projection update
         -> shared event/emission finalization -> frozen entity perception grants
         -> command/event/grants/outbox append -> derived cognition or narration
```

## Quick start

Requirements:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ with npm
- Docker with Compose v2 for durable operation

Install dependencies:

```powershell
uv sync --frozen
npm --prefix frontend ci
```

### Recommended: durable stack

```powershell
uv run python scripts/manage.py start
uv run python scripts/manage.py status
```

The manager creates a private `.env` with random database, Redis, and automation secrets; builds
the application; applies every migration; and waits for PostgreSQL, Redis, Qdrant, the API, and
worker. Open [http://127.0.0.1:8000/v2](http://127.0.0.1:8000/v2) and sign in.

Stop without deleting data:

```powershell
uv run python scripts/manage.py stop
```

Reset this Compose project's volumes and rebuild a fresh installation:

```powershell
uv run python scripts/manage.py start --reset
```

`--reset` permanently deletes this project's database, queues, vector collections, and artifact
volume. It does not target unrelated Docker volumes.

### Reference mode

Reference mode is useful for deterministic development without external services:

```powershell
npm --prefix frontend run build
uv run tabletop-dm doctor
uv run tabletop-dm serve
```

Open [http://127.0.0.1:8000/v2](http://127.0.0.1:8000/v2). Canonical state is process-local in
this mode, while file-backed experiment artifacts are stored beneath `artifacts/`. Use the durable
stack for restart guarantees, multi-process work, row-level security, and real queue execution.

For frontend development, keep the API running and start Vite in a second terminal:

```powershell
npm --prefix frontend run dev
```

Vite serves [http://127.0.0.1:5173/v2](http://127.0.0.1:5173/v2) and proxies `/api` to port 8000.

## Authentication and roles

Human browsers authenticate with a secure, HTTP-only `ttdm_session` cookie. Sessions last 12
hours. Five failed logins lock an account for 15 minutes; attempts during a lock neither extend
nor renew it, and the count restarts once the window lapses. Administrators can reset another
account to a temporary password, which forces that user to choose a new private password.

Roles are deliberately split:

- `ADMIN` is global and grants platform administration.
- `DM` is granted per world and enables Dungeon Master tools for that world.
- `PLAYER` is granted per world and enables Player tools for that world.
- A user may hold both `DM` and `PLAYER` in the same or different worlds.

Roles are never unioned across worlds: a grant in one world confers nothing in another, and a
world you hold no role in is not listed to you. Each account acts in the simulation only as its own
actor, so a proposal can never borrow another actor's capabilities or another actor's view of the
event ledger.

`TTDM_OPERATOR_TOKEN` remains available for local automation through the
`X-TTDM-Operator-Token` header. It is not the browser login flow and should not be distributed to
players.

## CLI

```text
tabletop-dm serve [--host HOST] [--port PORT]
tabletop-dm worker
tabletop-dm projector
tabletop-dm runner
tabletop-dm scenario [--cohort-size N] [--seeds ...] [--include-trials N]
tabletop-dm persona --seed SEED [--fixed JSON]
tabletop-dm population --size N --seed SEED --output FILE.parquet
tabletop-dm doctor
```

Examples:

```powershell
uv run tabletop-dm persona --seed 4815162342 --fixed '{"risk_tolerance":"LOW"}'
uv run tabletop-dm scenario --cohort-size 24 --seeds 101 202 303
uv run tabletop-dm population --size 10000 --seed 17 --output artifacts/people.parquet
```

## Health and verification

- `GET /healthz` proves the HTTP process is alive.
- `GET /readyz` checks migration state, PostgreSQL, Redis, and Qdrant when configured.
- `uv run python scripts/test.py fast` runs the function/contract and frontend fast gate.
- `uv run python scripts/test.py all` additionally runs integration and browser lanes against
  services that you started explicitly.

See [Testing](docs/TESTING.md) for the complete matrix.

## Documentation

- [Administrator, Dungeon Master, and Player setup guide](docs/ROLE_SETUP_GUIDE.md)
- [Simulation-kernel contract](docs/SIMULATION_KERNEL.md)
- [Battlefield control modes and renderer hooks](docs/BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md)
- [Spatial epistemics and perceived-scene contract](docs/SPATIAL_EPISTEMICS.md)
- [Architecture and invariants](docs/ARCHITECTURE.md)
- [Network and deployment diagram](docs/NETWORK_AND_DEPLOYMENT.md)
- [API and user workflows](docs/API_AND_WORKFLOWS.md)
- [Operations, storage, migrations, and security](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Repository guidance for coding agents](AGENTS.md)
- [Changelog](CHANGELOG.md)
- [Autonomous campaign implementation checklist](docs/AUTONOMOUS_CAMPAIGN_CHECKLIST.md)

## Conceptual influence, not a dependency

Some design ideas in TableTop DM were inspired by the publicly documented evaluation methods in
[MatrAIx](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B), particularly constrained persona
definitions, seeded cohort sampling, reproducible trials, task-specific verification, normalized
outputs, and population-level comparison. This acknowledgment concerns ideas and methodology—not
software integration.

TableTop DM does **not** contain or require MatrAIx source code, packages, runtime services, models,
datasets, schemas, Harbor stack, frontend, deployment artifacts, or Git submodules. It has no
MatrAIx compatibility or update relationship. The implementations in this repository were built
independently around TableTop DM's own deterministic persistent-world kernel, authorization model,
event ledger, spatial perception, cognition, tabletop domain, and scenario lab. You do not need to
download, install, or run MatrAIx to build or use TableTop DM.

Synthetic people and simulated player cohorts are tools for exploration, stress testing, and
hypothesis generation. They are not substitutes for evidence from real people.

## NPC population routines

Materialized population members can now be bound to existing world bodies and assigned recurring
gardening, rest, meals, home/work commutes, daily sleep and social commitments. The world clock
advances them while the
party is elsewhere, including rain interruptions, fatigue and food shortages. Opening a browser
does not start or stop work. A returning character sees physically perceptible activity and work.

This is opt-in setup through the typed API. Apply migration 011 with the migration owner, configure
the existing world clock/executor, then bind members and enable their routines. See
[population routines](docs/API_AND_WORKFLOWS.md#population-binding-and-npc-routines) for the workflow.
Home/work travel stays within one zone and elevation. Appointments can repeat, wait for participants,
or be missed; they do not invent dialogue or relationships. See
[travel, sleep and obligations](docs/API_AND_WORKFLOWS.md#travel-sleep-and-social-obligations).
General occupations, cross-zone routing, detailed activity planning and autonomous story direction
remain checklist work.

## License

See [LICENSE](LICENSE).

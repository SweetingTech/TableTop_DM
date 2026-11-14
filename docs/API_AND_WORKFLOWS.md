# API and user workflows

The Flask application serves the React client and a JSON API from the same origin. Browser pages
live under `/v2/*`; API resources live under `/api/v2/*`. UUIDs are serialized as strings and
timestamps use ISO 8601.

## Authentication

### Browser sessions

`POST /api/v2/auth/login` accepts a username and password. A successful response sets the
HTTP-only `ttdm_session` cookie with `SameSite=Lax`; HTTPS deployments also receive the `Secure`
flag. The server stores only a hash of the session token.

Login remains public but applies the same write-origin checks as authenticated browser writes.
Cross-site Fetch Metadata, a foreign or opaque Origin, and malformed Origin ports are rejected
before credentials can create a session cookie. Same-origin and headerless automation login work.

Useful routes:

| Method and route | Purpose |
| --- | --- |
| `POST /api/v2/auth/login` | create a 12-hour session |
| `GET /api/v2/auth/session` | return the authenticated account and role summary |
| `POST /api/v2/auth/change-password` | replace the current password and rotate sessions |
| `POST /api/v2/auth/logout` | revoke the current session and clear the cookie |
| `GET /api/v2/profile` | retrieve the current profile |
| `PUT /api/v2/profile` | replace editable profile fields |

The bootstrap `admin` / `admin123` credential is accepted only as an installation entry point.
That account has `password_change_required=true`; all protected application routes except session
inspection, password change, logout, and health return `403` until the password is replaced.

### Automation compatibility

Local automation may send `X-TTDM-Operator-Token` with the value configured in
`TTDM_OPERATOR_TOKEN`. The operator token is a machine-level compatibility boundary, not a user
account and not a substitute for player/DM role assignment. Requests without a cookie or token
are accepted only under the fail-closed loopback Host/Origin policy.

## Roles and authorization

- `ADMIN` is global.
- `DM` and `PLAYER` are assigned per world.
- A combined DM + Player account simply has both world roles.

The frontend hides unavailable workspaces, the API enforces the matching product role, the
simulation layer resolves world-scoped actor authority, and PostgreSQL RLS checks protected rows.
UI visibility is never treated as authorization.

## Discovery and health

| Method and route | Purpose |
| --- | --- |
| `GET /healthz` or `/api/v2/health/live` | process liveness |
| `GET /readyz` or `/api/v2/health/ready` | dependency and migration readiness |
| `GET /api/v2/meta` | runtime mode and contract metadata |
| `GET /api/v2/bootstrap` | worlds, active context, authenticated actor, and client bootstrap data |
| `GET /api/v2/commands/contracts` | registered typed command schemas |
| `GET /api/v2/personas/schema` | persona dimensions, dependencies, and constraints |

Readiness returns `503` with per-dependency details if a configured PostgreSQL, Redis, Qdrant, or
migration check is unavailable.

## Administrator workflow

1. Sign in and complete the mandatory password change.
2. Open Admin Dashboard and create accounts with a temporary password.
3. Assign `ADMIN` globally only when platform administration is required.
4. Grant `DM`, `PLAYER`, or both for each relevant world.
5. Create or inspect worlds, actors, entities, runs, snapshots, and trial branches in Control
   Plane.
6. Review append-only account activity in the admin audit view.

Account routes:

```text
GET    /api/v2/admin/users
POST   /api/v2/admin/users
PATCH  /api/v2/admin/users/{user_id}
DELETE /api/v2/admin/users/{user_id}
PUT    /api/v2/admin/users/{user_id}/password
PUT    /api/v2/admin/users/{user_id}/roles
PUT    /api/v2/admin/users/{user_id}/worlds/{world_id}/roles
GET    /api/v2/admin/audit
```

The final administrator cannot remove their own last admin role, disable themself, or delete
themself, and the last administrator who can still sign in cannot have their role removed, be
disabled, or be deleted by anyone. Disabled administrators do not count toward that guard, because
a disabled administrator cannot administer anything. Password resets revoke the user's active
sessions and require another password change.

Five failed logins lock an account for fifteen minutes. Attempts made during a lock are not
recorded, so they neither extend nor renew it, and the failure count restarts once the window
lapses — an account cannot be held locked by guessing at its username.

## Player workflow

1. An administrator grants the account `PLAYER` for a world.
2. The player opens Player Dashboard and chooses that world.
3. They create a character by:
   - building one from editable fields;
   - generating one deterministically from a seed; or
   - importing a JSON character template.
4. The dashboard displays class, ancestry, background, level, hit points, armor class, movement,
   ability scores, and `ALIVE`, `DEAD`, or `RETIRED` status.
5. A DM can assign that character to the player's game membership.

Routes:

```text
GET    /api/v2/player/characters
POST   /api/v2/player/characters
PATCH  /api/v2/player/characters/{character_id}
DELETE /api/v2/player/characters/{character_id}
GET    /api/v2/games
GET    /api/v2/games/{game_id}/sessions
```

Character writes are owner-scoped unless an administrator is acting through an administrative
flow. Imported templates are parsed and validated before persistence.

Character create/import and patch accept `authored_identity`: `backstory` (up to 12,000 characters)
and `motives`, `values`, `bonds`, `secrets`, `initial_known_facts` (each up to 20 nonempty strings
of 500 characters). Unknown identity fields, non-string entries, and over-limit input fail before
persistence. Whitespace is trimmed. Patch replaces the complete identity when supplied; omitting
it preserves the existing identity. An empty object clears it. Character sheet edits cannot use
the reserved `_authored_identity_v1` storage key. Legacy records receive an empty identity.

Responses include the typed identity and `card_version`, a SHA-256 content identifier over the
card schema, name, species, class, background, level, ability scores, and authored identity.
Wounds, status, ownership, world/body assignment, equipment, and timestamps do not alter this
identity version. This identifies current content; it is not an archive of prior cards or a
replacement for canonical entity state. Existing private JSON sheet storage persists the identity
without a schema migration. DM assignment lookups still return summaries only.

Starting knowledge is player-authored fiction, not a verified world fact or a sourced memory.
This change does not feed the identity into model prompts, minds, lore retrieval, or live decisions;
trusted approval and explicit persona/mind/body bindings remain required.

When a DM assigns a character to a game membership, the portal character is linked to a kernel
embodied entity. The player receives `entity.act` plus control of that specific body; this never
confers administrative `entity.control` over the world.

## Perception-scoped game workflow

The Player Game Console never reads canonical entity positions or the raw event ledger. It lists
authorized embodied viewpoints and loads a `PerceivedScene`:

```text
GET /api/v2/worlds/{world_id}/viewpoints
GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{entity_id}/scene
GET /api/v2/events/{event_id}/perceptions       # privileged inspection only
```

Normal prose submits `tabletop.dialogue.speak`, an embodied sound emission. Slash actions submit
their typed movement/combat/magic contracts; explicit OOC/interface text remains
`tabletop.console.submit`. The scene contains only current perceived entities and subjective
observation presentations, with detail levels from anonymous `PRESENCE` through `INSPECTED`.

Accepted embodied `POST /api/v2/commands` receipts include `scene_refresh` with `world_id`,
`branch_id`, `observer_entity_id`, `event_id`, and the committed `projection_version`. The client
reads the same scene with `?after_event_id={event_id}`; the response adds `refresh` containing
`event_id`, `ready`, and `observed`. Normal scene reads omit this metadata. Scene responses use
`Cache-Control: no-store`. The cursor is authorized for the submitting actor and exact body and
timeline; it grants no additional visibility. `ready` requires the expected subjective observation
when the frozen event-time grant produces one. Unperceived actions are ready without inventing
an observation. Durable reads hydrate a request-local mind snapshot from the RLS repository, so
separate projector processes are visible without replacing the API's shared projector cache.

The console polls every 200 ms for at most eight seconds after acceptance, requiring both the
canonical version and observation boundary. Only authorized observations enter the feed, keyed
by source event. A timeout or read failure reports that the action was accepted and offers a
read-only retry. Writes and post-acceptance reads never fall back to successful demo data.
World/viewpoint changes cancel pending reads and clear drafts, focus selection, and receipt state;
late command responses cannot populate the new viewpoint. This is per-action refresh, not yet
cross-client continuous updates.

## Dungeon Master workflow

1. An administrator grants `DM` for a world.
2. The DM creates a hosted game for that world.
3. They set status, description, player limit, safety notes, and house rules.
4. They invite eligible users as Player or Co-DM, assign characters, and track membership status.
5. They schedule sessions, update public notes, and maintain DM-only notes.

Routes:

```text
GET    /api/v2/games
GET    /api/v2/dm/worlds/{world_id}/eligible-users
GET    /api/v2/dm/games/{game_id}/users/{user_id}/characters
POST   /api/v2/dm/games
PATCH  /api/v2/dm/games/{game_id}
DELETE /api/v2/dm/games/{game_id}
PUT    /api/v2/dm/games/{game_id}/members
DELETE /api/v2/dm/games/{game_id}/members/{user_id}
POST   /api/v2/dm/games/{game_id}/sessions
PATCH  /api/v2/dm/games/{game_id}/sessions/{session_id}
```

DM notes do not appear in player responses. Co-DM membership requires the user's DM world role;
Player membership requires the Player world role.

The roster editor explicitly selects Player or Co-DM and supports assigning a character on
invitation or updating an existing member. Its character lookup requires game-host authority
and a target account with Player authority in that world; it returns only character ID, name,
class, level, and status for characters belonging to that player and either this world or no
world yet. It excludes character sheets and backstory. Assignment rejects missing characters,
wrong owners, and characters bound to another world. Choosing Co-DM clears the character selection.

Changing the selected user or membership role immediately clears old character choices and lookup
errors, and disables player saves until the new lookup settles. Obsolete responses cannot replace
the current user's choices. Changing games remounts the roster editor for that game.

## World and command workflow

Control-plane collections:

```text
/api/v2/worlds
/api/v2/actors
/api/v2/worlds/{world_id}/actors
/api/v2/worlds/{world_id}/entities
/api/v2/runs
/api/v2/worlds/{world_id}/runs
/api/v2/snapshots
/api/v2/worlds/{world_id}/snapshots
/api/v2/branches
```

Submit a typed command:

```http
POST /api/v2/commands
Content-Type: application/json

{
  "world_id": "...",
  "branch_id": "...",
  "run_id": "...",
  "embodied_entity_id": "...",
  "command_type": "tabletop.spatial.move",
  "parameters": {"dx": -1, "dy": 0},
  "idempotency_key": "player-turn-42-move-1",
  "seed": 42
}
```

The kernel validates that the run belongs to the world and branch, resolves the command schema,
checks world-scoped capability and entity control, commits one transaction, and returns a receipt
with state/event provenance. Reuse an idempotency key only to retry the exact same logical command.

### Battlefield control modes

The command registry includes engine-neutral hooks for one continuous battle world:

```text
tabletop.battlefield.set_control_mode
tabletop.battlefield.issue_squad_order
```

`set_control_mode` accepts `TACTICAL`, `THIRD_PERSON`, or `FIRST_PERSON`. It changes the
commander's control-mode projection without replacing the entity, weapon, health, squad, enemies,
or encounter. `issue_squad_order` accepts `FOLLOW`, `HOLD`, `FOCUS`, `SPREAD`, or `REGROUP` and
keeps follower AI active while the leader is under direct control.

Future renderers consume `BattlefieldFrame` values built from an explicit authorized visible
entity set and return `BattlefieldControlInput` values for translation into these and other typed
commands. Camera mode does not grant event or entity visibility. See
[Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md).

The acting actor is never taken from the request. A browser session always acts as the actor its
account owns, so `actor_id` may be omitted; sending a different one is rejected with
`permission_denied`. Only the operator token may name another actor, through the request body or
`X-TTDM-Actor-ID`, because automation has no account of its own. The same rule governs every route
that resolves authority or visibility from an actor: `GET /api/v2/events`,
`GET /api/v2/entities/{entity_id}/mind`, `POST /api/v2/cognition/decide`, and
`POST /api/v2/events/{event_id}/observe`.

Read visible events with `GET /api/v2/events?world_id=...&branch_id=...`. Create a snapshot-based
trial with `POST /api/v2/snapshots/{snapshot_id}/branches`, inspect replay with
`GET /api/v2/branches/{branch_id}/replay`, and submit an approved consequence package through
`POST /api/v2/branches/{branch_id}/promotions`.

### World-scoped reads

Every world-scoped route requires `ADMIN`, or a `DM` or `PLAYER` grant **for that world**. Roles
are never unioned across worlds, so a Player in one world reads nothing of another. Collection
routes (`/api/v2/worlds`, `/api/v2/runs`, `/api/v2/branches`, `/api/v2/snapshots`,
`/api/v2/events`) return only the caller's worlds rather than failing, so a world the caller
cannot read is invisible instead of merely unreadable.

`GET` and `POST /api/v2/actors` require `ADMIN`: an actor carries world capabilities, so minting
one is minting authority.

### Product roles and simulation capabilities

Product roles never *are* kernel capabilities; they are translated into explicit world grants by
`identity.repository.kernel_authority`, which is the single source of truth for both the durable
`sim.actor_capabilities` rows and the in-process authority table.

| Product role | Actor role | Capabilities |
| --- | --- | --- |
| `ADMIN` (global, every world) | `ADMIN` | world read, propose, commit, entity create/control, read secret, faction, divine, branch, evaluate, promote, mind read/write |
| `DM` (per world) | `GM` | the administrator set without `metric.evaluate` and `canonical.promote` |
| `PLAYER` (per world) | `PLAYER` | `world.read`, `action.propose`, `action.commit` |

A Player may therefore speak and act at the table, but holds no `entity.control`, so they can only
act through entities explicitly granted to their actor, and they can never read hidden state,
branch a run, or promote a trial. Granting or revoking a role re-provisions that actor's authority
for the caller's next sign-in.

## Persona and cognition workflow

Persona routes support list/create/generate, immutable version inspection, compilation, and
prompt assembly:

```text
/api/v2/personas
/api/v2/personas/generate
/api/v2/personas/{persona_id}
/api/v2/personas/{persona_id}/versions
/api/v2/personas/{persona_id}/compile
/api/v2/personas/{persona_id}/prompt
```

Generation records schema, generator, ruleset, seed, fixed values, and per-field provenance. A
compiled profile exposes policy weights and starting state without dumping the full schema into a
model prompt.

Cognition routes:

```text
POST /api/v2/cognition/decide
POST /api/v2/events/{event_id}/observe
GET  /api/v2/entities/{entity_id}/mind
POST /api/v2/entities/{entity_id}/relationships
GET  /api/v2/entities/{entity_id}/runtime
PUT  /api/v2/entities/{entity_id}/runtime
```

Observations must derive from visible canonical/trial events. Relationship changes require a
same-world, same-branch source event. A decision returns a trace and proposal; it does not mutate
world state until the proposal enters `/commands`.

Mind inspection applies the same server-side world and actor checks in reference and durable
storage. It requires the entity's controller or a world-scoped `mind.read.all`/`mind.write.all`
capability. A browser-supplied actor ID cannot borrow another actor's access.

## Population workflow

1. Generate a pool for an explicit world and branch.
2. Check cohort feasibility before a required-strata run.
3. Sample with fixed seeds and record weights/strata.
4. Materialize selected people.
5. Activate only people entering the relevance window.
6. Deactivate to a compressed persistent state when they leave it.

Routes are grouped below `/api/v2/populations`, including `definitions`, `generate`, `sample`,
`cohorts/feasibility`, `materialize`, member activation/deactivation, and transition history.
Lifecycle writes cannot retarget a pool to the currently selected UI world.

## Scenario, run, and calibration workflow

Scenario definitions are immutable `(scenario_id, version)` records. A run chooses an explicit
version or the greatest semantic version, snapshots the base world, creates isolated trial
branches, samples the cohort, executes trials, applies versioned verifiers, and aggregates facts.

```text
GET/POST /api/v2/scenarios
POST     /api/v2/scenarios/{scenario_id}/run
GET      /api/v2/jobs
GET      /api/v2/jobs/{job_id}
POST     /api/v2/jobs/{job_id}/cancel
POST     /api/v2/jobs/{job_id}/retry
GET      /api/v2/trials/{trial_id}
GET      /api/v2/reports
GET      /api/v2/reports/{report_id}
POST     /api/v2/trials/compare
```

Calibration is deliberately two-step:

1. `POST /api/v2/calibration/compare` creates a proposal from synthetic metrics and versioned
   evidence.
2. `POST /api/v2/calibration/{report_id}/review` records `APPROVED` or `REJECTED`.
3. `POST /api/v2/calibration/{report_id}/promote` registers an approved immutable version.

Promotion does not silently reassign any live entity runtime.

## Telemetry and privacy

Telemetry is disabled by default. Settings and capture routes live below `/api/v2/telemetry`.
Capture requires opt-in and a consent version. Sensitive keys are redacted. Export, import,
selective deletion, and retention purge are explicit operations. No external telemetry sink is
configured by this repository.

## Persona purpose

`POST /api/v2/personas` and `POST /api/v2/personas/generate` accept an optional `purpose`:
`CHARACTER` or `SIMULATED_PLAYTESTER` (the default for new identities). Manual successor creation
inherits the existing persona or parent version's purpose when omitted and rejects an explicit
purpose change; use a new identity for a different purpose. For example, generate an identity with
`{"seed": 31, "purpose": "CHARACTER", "fixed": {"risk_tolerance": "LOW"}}`.
Blueprint/detail/version and compile responses include the purpose. Invalid values return `400`
before saving a persona. Compile and prompt routes derive purpose from the stored blueprint;
they do not accept a purpose override. The existing Persona Studio generation form uses the
playtester default; explicit character-purpose selection is currently available through the API.

Character compilation includes core/world traits and excludes player/interface dimensions from
both deep traits and requested prompt traits. It seeds no onboarding goals, GM relationship,
interface capability, or evaluation retrieval filter. Playtester compilation retains existing
evaluation behavior. Purpose does not confer authority, bind a persona to a body, or validate
caller-supplied situation text; those are separate campaign knowledge/control requirements.

## Character context and evaluation boundary

`GET /api/v2/player/characters/{character_id}/history` returns immutable authored-card revisions
for the owner or an administrator. Each has `revision_id`, `revision_number`, `recorded_at`, the
authored `content`, and its existing deterministic `card_version`. Wounds, status, controller/body
association, and timestamps do not create card revisions. Deleting an unbound saved card also
deletes its private authored history; bound history is retained and the card can instead be retired.

An initial Player roster assignment automatically creates a character binding after the existing
typed body-spawn path. Existing bindings survive roster retries and card edits. Old installations
retain their current cards as revision 1; retrying a roster assignment initializes a missing binding.

```text
GET  /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-binding?run_id={run}
POST /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-binding
```

The POST body contains `character_id`, `run_id`, `card_revision_id`, optional `persona_version_id`,
and `replaces_binding_id` (null only for the first binding). The selected card must already be
associated with that world/body. The caller needs body control and `entity.act`, or world-scoped
`mind.write.all`, plus canonical commit/trial proposal authority. Selecting a persona never grants
control. Only `CHARACTER` profiles are accepted. Omitting a persona selects a deterministic
card-seeded baseline; it is not semantic backstory inference or human-history imitation.

Bindings pin the exact compiled persona version/compiler and an immutable card revision, with
composite world/branch/run/body/mind lineage. Replacement uses compare-and-swap: a stale parent
fails; an identical retry returns the original binding without making an old binding current.
Concurrent replacements serialize, and a failed first binding rolls back neutral-mind creation.
Existing memories, beliefs, relationships, goals, and runtime assignments are preserved. Binding
is private controller configuration; it emits no sensory event and changes no canonical projection.
These operations do not make the existing roster/spawn operation atomic (checklist A2).

`GET /api/v2/worlds/{world_id}/branches/{branch_id}/entities/{entity_id}/context` uses the same
world/viewpoint authorization as the perceived scene. It returns a versioned evidence hash,
projection version, and a model-facing `situation`. Frozen event-time grants and source events
must match the observer/world/branch; operator-tagged events, unbacked beliefs, and memory-summary
overrides cannot add facts. The model-facing situation excludes controller, ledger, and timeline
metadata. Context version `character-context-1.1.0` includes the pinned self-authored identity only
when the caller controls the body or holds `mind.read.all`; broad scene inspection alone does not
grant private identity access. `binding` is operational response metadata outside `situation`.
The situation's `identity` contains fiction and explicitly labeled `starting_knowledge_claims`;
authored claims are not added to observations, beliefs, memories, or canonical truth. Other bodies'
secrets, binding IDs, account/control settings, and persona/compiler IDs never enter that fiction.
Specify `?run_id={run}` when reading a non-default run; multiple live runs require explicit selection.
This endpoint is read-only. `action_candidates` currently contains four typed cardinal
movement attempts when the caller controls this body, holds the command's world-scoped capabilities
(including canonical commit authority), and the perceived self has a position and no known
incapacity. Inspect-only viewpoints return no executable choices. `action_catalog_version` is
`tabletop-character-actions-1.0.0`. Candidates carry typed command parameters outside `situation`;
their action labels contain fiction only. There are no class/species/protagonist restrictions.

These choices are attempts, not guaranteed outcomes. The provider never reads hidden obstacles
or hidden entities to remove choices; otherwise the catalog itself would reveal unknown facts.
The kernel must revalidate authority, lineage, and rules on submission. No model or read request
commits an action. Speech/combat/activity catalogs and learned lore remain planned. Durable reads
hydrate fresh canonical and subjective projections. The context read itself does not wait for
dependent observations; trusted proposal generation and the runner enforce that barrier before
choosing an action.

`POST /api/v2/cognition/decide` accepts caller-authored situations/actions only for privileged
`SIMULATED_PLAYTESTER` evaluation (administrator session or automation boundary, still subject to
world/body checks). Its response identifies `mode: EVALUATION` and `committed: false`.
Other browser accounts and `CHARACTER` personas receive `403`. Trusted character proposals
use the server-owned binding and context; the evaluation request cannot invent a binding by
choosing a persona ID. Binding alone does not enable live decisions. Human Game Console commands
continue through their existing kernel path.

### Trusted character proposals

`POST /api/v2/worlds/{world}/branches/{branch}/entities/{body}/character-proposals`
accepts only `{"run_id": "{run}", "idempotency_key": "logical-decision-key"}`. Unknown fields,
including situations, actions, personas, runtime configuration, and seeds, are rejected.
The caller must control this body and hold its world-scoped movement/proposal capabilities,
including commit authority on a canonical branch. DM inspection authority alone is insufficient.
New decisions require an active run and an exact version-pinned CHARACTER binding.

The server assembles the same trusted context as the context read, then uses the pinned compiled
persona and versioned basic movement catalog with local deterministic utility policy. This initial
policy has no narrative planner or player-behavior imitation. No provider/model calls occur.
Before generation, every sensory event with a frozen grant for this body must have its dependent
observation persisted. Otherwise the response is `409 character_context_pending`; retry the same
key after projection catches up. Operator records are outside this barrier and character fiction.

The response contains `authorship: CHARACTER_POLICY`, `execution_mode: PROPOSAL_ONLY`,
`committed: false`, pinned binding metadata, evidence hash, versions, server-derived seed,
and `outcome.proposal`. Operational provenance is outside the model-facing situation. Receipts
contain no context/backstory copy. This is policy-generated evidence, never human preference data.
The same world/branch/run/body/actor/key returns the original receipt, even after world changes,
rebinding, or a durable restart; current body control/capabilities are checked again before retry.
Use a new key for a new decision.

Migration 006 stores each immutable private receipt and decision trace atomically. Requests serialize
on the authorized run and branch; a request-local durable snapshot avoids stale worker caches.
Reference mode serializes proposal reads against command publication. A receipt does not grant
permission to execute later. Submit `outcome.proposal` through `POST /api/v2/commands` to request
normal kernel revalidation and idempotent execution. The proposal endpoint never advances time,
changes runtime assignments, or automatically submits a command. The separate controller/runner
workflow below adds exclusive epochs and bounded scheduling. Broader actions, learned lore, and
player-history imitation remain planned.

## Controller handoff and runner

`GET /api/v2/worlds/{world}/branches/{branch}/entities/{body}/control?run_id={run}` reads private
controller status for the body owner or a world-scoped `mind.write.all` operator. An unconfigured
body returns `control: null`; use expected epoch zero for its first handoff.

`POST` to the same path accepts only:

```json
{
  "run_id": "UUID",
  "expected_epoch": 0,
  "mode": "AUTONOMOUS",
  "idempotency_key": "one-logical-handoff",
  "max_steps": 20,
  "interval_ms": 1000
}
```

Modes are HUMAN, AUTONOMOUS, and PAUSED. Handoffs are restricted to canonical LIVE runs. The owner
or authorized operator must hold execution capabilities before enabling autonomy. The action
budget is 1–1,000 and interval is 100–60,000 ms. Each handoff increments the exclusive controller
epoch; a stale expected epoch returns `409 controller_changed`. Retry an uncertain operation with
its original key. The browser rereads current control so an old receipt cannot overwrite later state.

The body retains its human owner, persona, pinned card, and mind. A separate AGENT receives minimal
world capabilities and entity-scoped private context/command grants. Its proposals and ledger rows
carry CHARACTER_POLICY authorship, controller epoch, step, and decision-trace/pinned-identity
attribution. They are not human preference evidence. Handoffs have private append-only receipts,
never emit sensory events, and do not change the character context hash.

Every new managed command must carry the epoch observed by its controller. The typed console
adapter sends `control_epoch`; autonomous commands also carry `control_step`. The server never
upgrades a delayed command by stamping a fresh epoch. Unmanaged legacy bodies retain their
existing behavior. Kernel fencing occurs inside the same branch/state lock as canonical mutation.
Old controllers cannot act after takeover; committed retries cannot advance the world or step twice.

`python main.py runner` processes due autonomous controllers using trusted pinned context and
local utility/movement candidates, then submits through the normal kernel. No provider call or
browser cookie is used. The canonical commit and step/budget advance share one database transaction.
Epoch/step proposal keys survive crashes and concurrent workers. Observations still flow through
the frozen perception outbox; the next decision waits for them. Invalid actions pause with
`action_failed`; pending observations defer every 250 ms and pause after 40 unsuccessful checks.
The budget pauses with `step_limit`. Resume explicitly with a new handoff/key/current epoch.

The Game Console exposes Let character act, Pause autonomy, Take control, and an action limit.
It polls status, refreshes the authorized scene on progress, and disables human submission until
takeover. Saved mode survives browser closure and process restart. Closing a browser while HUMAN
does not enable autonomy. Presence timeouts/reconnect policies, human-history inference, richer
actions, narrative goals, and the canonical world clock remain separate work; due times here are
operational wall-clock scheduling only.

Runtime GET reads durable assignments fresh and adds controller metadata for managed bodies.
Handoff atomically selects HUMAN or UTILITY while preserving runtime configuration. Legacy runtime
PUT cannot bypass explicit handoff for a managed body.

## Error contract

Errors use a JSON body with a stable `error` code and, where safe, a human-readable detail.
Common status meanings:

- `400`: invalid input, invariant violation, or invalid lifecycle transition;
- `401`: no valid browser session or automation token;
- `403`: password change required, missing role/capability, invisible evidence, or disallowed
  branch operation;
- `404`: resource is absent or not visible to the caller;
- `409 character_context_pending`: retry character advice after subjective projection catches up;
- `409 controller_changed`: reload control before making a new logical handoff;
- `409`: idempotency, uniqueness, version, or state-hash conflict;
- `503`: configured dependencies or migrations are not ready.

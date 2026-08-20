# API and user workflows

The Flask application serves the React client and a JSON API from the same origin. Browser pages
live under `/v2/*`; API resources live under `/api/v2/*`. UUIDs are serialized as strings and
timestamps use ISO 8601.

## Authentication

### Browser sessions

`POST /api/v2/auth/login` accepts a username and password. A successful response sets the
HTTP-only `ttdm_session` cookie with `SameSite=Lax`; HTTPS deployments also receive the `Secure`
flag. The server stores only a hash of the session token.

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
themself. Password resets revoke the user's active sessions and require another password change.

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
  "actor_id": "...",
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

Read visible events with `GET /api/v2/events?world_id=...&branch_id=...`. Create a snapshot-based
trial with `POST /api/v2/snapshots/{snapshot_id}/branches`, inspect replay with
`GET /api/v2/branches/{branch_id}/replay`, and submit an approved consequence package through
`POST /api/v2/branches/{branch_id}/promotions`.

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

## Error contract

Errors use a JSON body with a stable `error` code and, where safe, a human-readable detail.
Common status meanings:

- `400`: invalid input, invariant violation, or invalid lifecycle transition;
- `401`: no valid browser session or automation token;
- `403`: password change required, missing role/capability, invisible evidence, or disallowed
  branch operation;
- `404`: resource is absent or not visible to the caller;
- `409`: idempotency, uniqueness, version, or state-hash conflict;
- `503`: configured dependencies or migrations are not ready.

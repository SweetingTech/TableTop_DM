# Operations, storage, migrations, and security

Apply migration `016_decision_origins.sql` before rolling out the application and runners. It
extends the existing private command ledger constraint and applies without rewriting old origins.
Keep the application and runner on the same build so fresh decisions record matching provenance.

Deploy the same application version across character runners. They use the existing durable
controller failure count to fence rejected attempts and resume replanning after restart. No
schema migration is required. Inspect the private controller status for `action_invalidated`,
`action_failed`, or `step_limit` when a character stops.

The worker restores personal recovery plans from existing private proposal receipts and committed
command records. A restart uses the same controller epoch and due time. Preserve those records
with the branch and mind stores when restoring a durable campaign.

Scheduled replies use the existing controller and perception records. A new worker waits for
the source observation to publish and recovers the reply from that evidence. Inspect the exact
branch's projector status when private control reports `character_context_pending`.

Apply migration 014 before starting the updated application and world runner. It backfills due
work for running canonical clocks. The worker leases steps for 30 seconds on database time and
uses exponential retry delays capped at 60 seconds. Current world grants restrict queue access
to authorized managers and the assigned executor. Existing Compose services and settings apply.

The projector processes each branch's outbox in order. Inspect that branch's first unpublished
row when later observations are waiting. Its retry timestamp and stable error class identify the
pending event while other branches can continue. Restarting the projector recovers expired
claims and reuses any observations already written for the event.

Receipt grant freshness needs no migration, grant or stored-result rewrite: the durable API calls
the existing protected `sim.has_world_capability` function with the submitting actor set locally
on the read transaction. Deploy the matching API/control-plane code. Role changes from a second
API process take effect for private receipt inspection without restarting the first process or
hydrating all campaign state on every command. Canonical command authorization remains in the kernel.

Quest/offer receipt privacy requires the matching API update. There is no migration or stored
receipt rewrite: nonprivileged HTTP responses omit private projection deltas, while exact-world
read-all operators retain full diagnostic receipts. Do not elevate players to recover internal
delta access; use perceived scenes and the public typed action result.

Quest contracts use existing atomic branch projections, with no migration or separate worker.
Deploy matching Python/SPA versions. Create funded contracts through manager-only typed commands;
do not migrate legacy caller-reported quest counters into verified objectives. Old committed
keys still return their original canonical receipts, while new `quest.advance` requests accept
only a quest ID. No model/provider writes progress or rewards. Existing world clock commands
produce offscreen work evidence atomically; failed publication rolls back both work and progress.
Claim/cancel are terminal reserve settlements, and historical rows do not consume active quotas.
Ordinary healing cannot restore a dead giver: continuation after such a death remains governed
by the existing director/rewind checklist work rather than a reward bypass.

Trade offers use existing atomic branch projections; no migration, provider or new worker is
required. Deploy the matching Python code and built SPA together: new trade requests reference
maker-authorized offers instead of setting price/direction. Old committed keys retain their
canonical receipts. The shared clock advances offer expiry and refunds; clockless offers anchor
their lifetime when the clock first advances. Reservations remain with the maker's physical body,
not a remote exchange. Managers seed standing offers through typed configuration over existing
goods/funds. Do not backfill client-invented prices into offers or mint replacement inventory.

Ability-derived attacks/loadouts require no migration or new process. Newly bound characters
receive scores/proficiency/training as canonical starting definitions. Existing scoreless bodies
keep their explicit legacy combat profile; configure them deliberately with the typed manager
`tabletop.body.configure` command when their intended scores/training are known. This operation
does not infer card stats, create equipment, heal or refill resources. Bound-card score edits stay
rejected; the player sheet reads current body scores and bonuses through its existing live API.

Initiative needs the existing configured world clock and no new service/migration. World managers
use typed `tabletop.encounter.start`/`stop` commands; the manager role remains distinct from body
control. Participants can miss windows while the clock continues; pausing the clock pauses their
schedule and offscreen work together. Stop a stale prior-run encounter before beginning a new
one with those bodies. Stopping preserves body readiness and append-only evidence. Starting
character ability scores are body-owned after binding, so card patches cannot change them.

Rest uses the existing world clock; there is no new process or migration. Start a configured clock
or advance its paused simulated time to progress rest and NPC sleep. New character bodies carry
canonical maximum mana. For legacy bodies, explicitly configure known HP/mana caps through the
world-manager typed `tabletop.resources.configure` command; never refill by editing an authored
card. Capacity changes preserve current resources and reject caps below the current amount.

Death saves reuse existing canonical projection storage; no new service, credential or migration
is needed. Deploy matching recovery, clock, perception, API and runner code with the rebuilt
console bundle for `/stabilize`. Both spell entry points now record trusted physical RNG provenance;
canonical embedders must retain the existing trusted run-seed reader. Saved defeat seeds survive
restart, retry and clock reconfiguration. Existing zero-HP bodies are not retroactively rerolled.
Private `tabletop.vitals` records are operator evidence, not character sensory facts. Do not
publish them through a custom renderer or model context. Old event-time grants remain unchanged.

Timed effects reuse the existing body projection store and require no migration or provider setup.
Deploy matching rules, clock handlers and character/world runners together. New timed conditions
require a clock; permanent conditions remain separate. Existing blessing records lacking absolute
expiry receive a deterministic expiry from their remaining turns at the beginning of the first
new clock advance, not on reads. Backups/replay keep original receipts and deltas. Do not run a
one-off database backfill or clear source maps to recover a character: use authorized timeline or
world commands. Routine policy1.4.0 and daily planning1.2.0 record the new blocked-work semantics.

Action timing reuses the existing projection store; no migration, new service or provider is
required. Deploy the command handlers and character/world runners together. Configured clocks
now pace actions in simulated time, independent of controller `interval_ms` (which remains a
poll/due bound). Set `seconds_per_tick` to the desired simulation speed; a paused clock requires
authorized advance/resume before reserved actions become ready. Do not remove readiness rows or
backfill authored card values to accelerate a character. Clockless legacy worlds stay untimed.
Existing recorded receipts/replay deltas remain valid after upgrade. Fresh trials inherit
physical readiness but require their own clock/run configuration before new timed actions.

Older clients must stop sending physical resource/status edits through the card PATCH route for
bound characters; such requests now fail400 before metadata/history writes. Do not backfill card
HP from bodies or bypass the guard for administrators. World actions own live resources. No
migration, role/capability change, service, configuration or provider setup is needed. The
Dashboard hides bound-card editors and shows the typed live projection.

Canonical character-state reads reuse schema012 and current card/entity/control stores. No
migration, index, service, model or configuration change is required. The endpoint hydrates a fresh
durable snapshot and checks current ownership/world/body authority; restart does not require card
resource backfill. Keep its private allowlisted response out of shared caches (including errors).
The Dashboard consumes this projection and the card update API enforces separate resource ownership.

The shared voluntary-action policy is recorded with `voluntary-body.1` and `action-time.1` in command versions.
No migration, worker, environment variable or frontend source update is required. Historical
committed receipts still precede validation; retry them normally after upgrade. New invalid
incapacitated actions leave no writes. A failed wake attempt does not change sleep state.

Explicit CHARACTER cognition requests reuse schema006 proposal receipts and current schema012;
no backfill, migration, credential or model configuration change is needed. Scope/actor/key are
shared with the existing character-proposals route, including durable restart retries. This route
does not activate a runner or grant control. Caller-authored evaluation remains privileged.

Attack handler 2.1.0 uses recorded per-action RNG proofs with schema 012 unchanged. New omitted
run seeds persist as zero; existing null seeds retain storage identity and resolve to zero for
mechanics. Previously committed receipts are returned unchanged, including receipts without RNG
proofs. No backfill, resource reset, new service or provider setup is required. Keep the private
canonical receipt/ledger separate from character-facing observations when exporting diagnostics.

Combat/cast/invoke request contracts are now 2.0.0: use target-only melee and registered spell ID
plus target. Merge and deploy the paired backend and console changes with their current compiled
bundle together; the preceding console's `/cast` adapter is incompatible. Committed historical keys
retain their original receipts; regenerate uncommitted advice containing retired dice/bonus or
power/cost fields. Initial spell knowledge comes from the validated card sheet; live body state
owns subsequent resources/knowledge. This change reuses schema 012 and existing workers/stores.

Character knowledge retrieval is read-only and reuses schema 012 plus existing actor-scoped mind
and binding stores. No service, credential or additional index is required. Keep the perception
projector running: context/retrieval/proposals return `character_context_pending` (409) while
physical evidence is pending. Repair the projector rather than bypassing that barrier. Broad
world/scene inspection does not grant private mind or learned-lore access. Card edits affect
starting knowledge only after an explicit binding successor; no history is silently rewritten.

## Runtime profiles

### Durable stack

Durable mode is the supported operational profile. Compose defines nine services:

- `postgres`: canonical and application records;
- `redis`: authenticated RQ queue transport;
- `qdrant`: semantic lore/retrieval storage;
- `migrate`: one-shot owner-credential migration job;
- `app`: unprivileged Flask API plus compiled React assets;
- `worker`: unprivileged experiment worker.
- `projector`: frozen world-event perception and cognition projection;
- `runner`: bounded character executor, idle until explicit autonomy opt-in.
- `world-runner`: persistent time/offscreen activity driver, idle until explicit clock opt-in.

Start and verify:

```powershell
uv run python scripts/manage.py start
uv run python scripts/manage.py status
```

Stop while retaining named volumes:

```powershell
uv run python scripts/manage.py stop
```

Remove this Compose project's named volumes:

```powershell
uv run python scripts/manage.py stop --volumes
```

Start from an empty installation:

```powershell
uv run python scripts/manage.py start --reset
```

`--reset` and `stop --volumes` are destructive to TableTop DM data. Back up PostgreSQL and the
artifact volume first.

### Reference mode

```powershell
npm --prefix frontend run build
uv run tabletop-dm serve
```

Without `DATABASE_URL`, the API uses in-memory repositories for canonical state and identity.
This mode is for deterministic development and tests. It is not a substitute for durable
multi-process behavior or database authorization.

## Managed configuration

`scripts/manage.py` creates or upgrades `.env` without overwriting existing secrets. New
installations receive random values for:

- `POSTGRES_PASSWORD`;
- `APP_DATABASE_PASSWORD`;
- `REDIS_PASSWORD`;
- `TTDM_OPERATOR_TOKEN`.

`.env` is ignored and should remain readable only by the local account. `.env.example` contains
disposable loopback values for CI and isolated test stacks; do not deploy those values.

Important variables:

| Variable | Purpose |
| --- | --- |
| `DATABASE_ADMIN_URL` | owner connection used only by migrations |
| `DATABASE_URL` | least-privilege API/worker connection |
| `REDIS_URL` | authenticated RQ connection |
| `QDRANT_URL` | Qdrant HTTP endpoint |
| `TTDM_ARTIFACT_ROOT` | snapshot/report/population artifact root |
| `TTDM_LLM_MODE` | `mock` by default; provider selection for optional deliberation |
| `TTDM_RNG_SEED` | deterministic default seed |
| `TTDM_OPERATOR_TOKEN` | automation compatibility credential |
| `TTDM_TELEMETRY_ENABLED` | initial local telemetry switch; off by default |
| `CORS_ALLOWED_ORIGINS` | optional explicit browser-origin allowlist |
| `APP_BIND_ADDRESS` | published API address; defaults to `127.0.0.1` |

The Compose network uses service DNS names (`postgres`, `redis`, `qdrant`) internally. Host-side
URLs generated by the manager use `127.0.0.1` to match hardened IPv4 loopback publishing.

## Optional decision model

Set `TTDM_DELIBERATION_MODE=openai-compatible` to enable model-assisted action selection. Set
`TTDM_DELIBERATION_BASE_URL` to the server's API base, usually ending in `/v1`, and select
`TTDM_DELIBERATION_MODEL`. Configure `TTDM_DELIBERATION_API_KEY` on the server if the endpoint
requires authentication. Use `LOCAL_LLM` or `HOSTED_LLM` for `TTDM_DELIBERATION_RUNTIME_KIND`.
The default mode is `off`. Dialogue has its own `TTDM_DIALOGUE_*` configuration.

The decision model receives at most 32 KiB of request JSON. The time budget defaults to ten
seconds across one initial attempt and at most one retry for transient failures. Set
`TTDM_DELIBERATION_TIMEOUT` up to 30 seconds and `TTDM_DELIBERATION_MAX_TOKENS` from 32 to 1,024.
The optional token-parameter, JSON mode and seed settings are listed in [the environment example](../.env.example).
If the endpoint is busy, unavailable, incompatible or slow, the runner uses its deterministic
utility choice. Inspect private decision traces for model selection, request counts and measured
token usage. The trace uses a stable selection explanation. Credentials stay in the server environment.

## First sign-in and account recovery

On an empty identity store, the application creates one administrator:

```text
username: admin
password: admin123
```

The account cannot enter the application until it replaces that password. After bootstrap:

1. create a second administrator before changing deployment ownership;
2. create individual DM and Player accounts rather than sharing credentials;
3. grant world roles only where needed;
4. use Admin Dashboard password reset to issue a temporary password;
5. disable an account when access must stop immediately.

Sessions last 12 hours. Five invalid attempts lock an account for 15 minutes. Password changes,
resets, disabling, and deletion revoke applicable sessions. The final administrator cannot remove
the last path to platform administration.

The operator token is not an account-recovery password. It is intended for controlled local
automation and test clients.

## Health and readiness

`GET /healthz` checks only that the HTTP process can respond. `GET /readyz` verifies configured
dependencies and returns `503` if any required check fails.

The durable control plane retains its established bootstrap actor across metadata synchronization
and hydration. It never selects a different world's actor merely because authority rows reorder;
losing the bootstrap authority fails closed without widening grants.

Durable readiness includes:

- PostgreSQL runtime connection;
- migration history through `013_roster_controller_revocation.sql`;
- Redis authentication and ping;
- Qdrant HTTP readiness;
- active durable storage mode.

Useful diagnostics:

```powershell
uv run python scripts/manage.py status
docker compose --env-file .env -f infra/docker-compose.yml ps
docker compose --env-file .env -f infra/docker-compose.yml logs --tail 200 app worker migrate
uv run tabletop-dm doctor
```

Never paste `.env`, cookie values, password hashes, private DM notes, or entity secret state into
issues or logs.

## Migrations

Migration files live in `infra/sql/migrations/` and are applied in numeric order. The migration
runner records SHA-256 checksums and fails closed if an applied file changes.

Rules:

1. Never edit an applied migration.
2. Add the next numbered SQL file.
3. Make fresh install and upgrade produce the same schema.
4. Add an integration test for constraints, grants, triggers, and RLS.
5. Run migrations with the owner URL; never give owner credentials to the API or worker.
6. Keep `scripts/verify_wheel.py` aware of packaged migration expectations.

Run explicitly:

```powershell
uv run python infra/migrate.py --check
uv run python scripts/manage.py migrate
```

Compose runs `migrate` before `app`, experiment `worker`, world-event `projector`, and character
`runner`. Managed startup includes all four runtime services.
Readiness verifies the latest migration rather
than assuming the one-shot container succeeded.

## PostgreSQL authorization

The owner creates schemas, functions, policies, and the runtime role. The API and worker connect
as the non-owner `tabletop_runtime` login, which inherits the no-login `tabletop_app` role.
Public schema access is revoked.

Forced RLS protects canonical projections, entities, command/event ledgers, cognition records,
runtime assignments, relationship changes, and telemetry captures. Actor-aware transactions set
the transaction-local `app.actor_id`; missing, unknown, or malformed context yields no protected
rows.

RLS is defense in depth. Product routes still enforce account roles and ownership, and the
command bus still validates actor capability, entity control, run lineage, branch kind, and
typed parameters before a handler runs.

## Immutable and append-only records

Database triggers prevent rewriting evidence such as:

- command and event ledgers;
- identity audit entries;
- persona blueprint versions and compiled profiles;
- observations, memories, decision traces, and relationship-change history;
- verifier facts and normalized metrics.

Telemetry captures reject updates but allow authorized deletion for consent withdrawal and
retention expiry. Corrections elsewhere use successor records rather than rewriting history.

The durable command transaction owns:

1. branch row lock and current projection load;
2. validation and deterministic handler execution;
3. next projection/version/hash;
4. command receipt;
5. event envelope;
6. outbox record;
7. idempotent entity materialization when requested by the command.

Any error rolls the transaction back.

Migration `004_persona_purpose.sql` adds validated persona purpose to blueprints and compiled
profiles and a composite foreign key requiring each profile to match its blueprint purpose.
Existing rows default to `SIMULATED_PLAYTESTER`; their immutable content hashes, version IDs,
and old compiled profiles remain intact. New character versions include purpose in their identity.
Compiler `persona-compiler-0.3.0` produces purpose-specific profiles. Upgrade the schema before
starting this application version; readiness rejects the previous migration boundary. Existing
runtime grants and append-only triggers continue to apply to the added columns.

Compiled-profile retries compare every persisted content field at the exact persona/version/compiler
key. Identical retries succeed; differing identity, policy, goals, beliefs, relationships, routines,
capability modifiers, retrieval filters, or purpose fail without replacing the immutable profile.

## Storage and retention

Migration `005_character_history_and_bindings.sql` backfills each existing saved card as private
revision 1, then archives authored changes through a trigger in the card transaction. It adds
append-only binding metadata with composite card/run/entity/mind/profile foreign keys, forced RLS,
and serialized successor checks. Runtime can read permitted revisions but cannot insert or rewrite
them directly. The migration does not auto-create personas for old characters; retry their roster
assignment to create a missing initial binding. Existing bindings are never silently replaced.

Apply migrations through 012 before starting this application version. Back up PostgreSQL and artifacts and verify
the upgrade in an isolated restore first, using the normal schema-change procedure below.
Unbound card deletion explicitly erases its private authored history. Bound revisions and bindings
are retained; retire the saved card instead of deleting evidence beneath a running identity.
Account/persona/body/mind/runtime identities remain separate. No model credentials are required.

Migration `006_character_proposal_receipts.sql` adds private append-only character-policy receipts
with composite binding/trace lineage, actor-scoped forced RLS, and SELECT/INSERT-only runtime
grants. Receipt and trace insertion share one transaction; failure leaves neither record.
It supports a clean install and upgrade from 005. Advice uses local policy, adds no provider,
worker, port, or automatic runtime assignment, and writes no canonical event or projection.
Back up receipts with cognition and the canonical database. Do not roll back by deleting receipts
or rewriting migration history; restore an isolated verified backup for schema rollback.

Migration `007_controller_handoff_runner.sql` adds private forced-RLS controller projections,
append-only handoffs, AGENT/epoch guards, scoped executor grants, and ledger authorship/epoch/step.
It supports clean installation and upgrade from 006. Existing runtime assignments do not become
autonomous automatically. Back up controllers and handoffs with runtime assignments, receipts,
and canonical history; existing snapshots/trials are not complete campaign checkpoints.

The runner uses the existing runtime database URL and artifact volume; no model credential or
new port is required. It acts through a dedicated AGENT, never a browser cookie. The projector
must deliver observations for successive decisions. Missing/stuck projection causes bounded
deferred attempts and an explicit controller pause. Default budget is 20 actions at one-second
intervals; maximum budget is 1,000. A restart preserves mode, epoch, step, and remaining budget.
Browser disconnection preserves the selected mode. Use Pause autonomy or Take control to stop
character execution. Worker-health/throughput dashboards remain planned.

The world-runner uses the runtime database role and artifact volume, with no new port, credential
or SQL migration. Managed startup includes it. Existing clocks stay absent/idle until an operator
configures an explicitly granted AGENT; see [world time](API_AND_WORKFLOWS.md#world-time-and-offscreen-activities).
Stop it by pausing the clock through a typed configure command. That also suspends unattended
characters; explicit human/operator commands remain possible. FREEZE is the default downtime
policy; choose CATCH_UP explicitly if missed ticks should be processed, bounded per commit.
Neither starts a full narrative campaign or attaches statistical population records automatically.
Back up clock/activity/weather projections with their canonical ledger, grants and artifact volume.
Existing projection snapshots contain them, but remain incomplete whole-campaign checkpoints.

| Data | Store and recovery notes |
| --- | --- |
| Accounts, roles, sessions, audit | PostgreSQL; back up with canonical state |
| Worlds, branches, projections, actors, entities, runs, ledgers | PostgreSQL; replay hashes verify restoration |
| Characters, hosted games, members, sessions, DM notes | PostgreSQL; private fields remain server-side |
| Persona versions and compiled profiles | PostgreSQL; source schema remains in package YAML |
| Cognition and runtime assignments | PostgreSQL with actor-scoped RLS |
| Population catalog/lifecycle | PostgreSQL; large pool bodies are Parquet artifacts |
| Scenario/job/trial/report catalogs | PostgreSQL plus immutable artifacts |
| Snapshots and calibration records | artifact volume, referenced by URI and hash |
| Queue delivery | Redis; immutable job state remains outside queue transport |
| Semantic retrieval | Qdrant; source lore should remain reproducible |
| React bundle | immutable image/package asset under `static/v2` |

Telemetry is disabled until opt-in. Captures record a consent version, redact sensitive keys,
and support export, selective delete, and retention purge. This repository does not transmit
telemetry to a third party.

## Backup and restore

Migration `010_tactical_choice_evidence.sql` extends the existing private evidence constraint and
source trigger for guard/fixed spells and the new choice version. It retains old evidence and
append-only/RLS/privilege rules. Apply it through the owner before upgrading API/runner processes.

Apply migration 015 before enabling the scoped narration routes on a durable stack. Narration
entries use the existing PostgreSQL runtime role and are append-only. Existing projector lag can
delay character and spectator lines until their masked observations reach storage.

Before resuming a paused character, inspect its controller `last_error`. Recovery pause codes
identify repeated backtracking, ineffective melee, or an exhausted reply chain. An explicit
handoff starts a new controller epoch under the existing action budget.

Generated dialogue is off by default. To activate it, choose the endpoint/model and compatibility
settings in [.env.example](../.env.example); see [the workflow](API_AND_WORKFLOWS.md#generated-dialogue-and-tactical-choices).
API and runner must share configuration. The provider key remains server-only; there is no implicit
reuse of OPENAI_API_KEY, no model discovery and no startup network probe. No real provider/model
was selected by the feature. Bounded HTTP failures produce a private FALLBACK receipt without raw
provider errors or credential-bearing URLs. In-process retries are disabled. Proposal locks can
be held up to the configured provider timeout (maximum 30 seconds).
The main decision also enforces a total deadline. Late transport responses are discarded; at most
two transport workers can remain in flight per process. They have no kernel/storage authority.
An already-sent provider request may still complete after fallback and incur its bounded token cost.

Migration `009_speech_combat_evidence.sql` adds a separate private forced-RLS append-only choice
evidence table with source, option and composite binding guards. It supports clean install and
upgrade from 008, preserving 008 rows and profile hashes. Back it up with canonical events, bindings
and proposal receipts. It adds no service, port or provider. New speech evidence stores classified
intent/volume and perceived options rather than utterance text. Apply with the migration owner;
the runtime retains SELECT/INSERT only. This change does not auto-enable any controller.

Migration `008_player_behavior_evidence.sql` adds private, forced-RLS, append-only human movement
evidence and independent command input origin. It supports clean install and upgrade from 007.
Existing commands stay UNSPECIFIED and are not training examples. Back up evidence with its source
events, bindings and proposal receipts; profile versions are content-addressed and frozen in those
receipts. There is no new service, port or provider. Keep migration-owner and runtime roles separate.

Back up PostgreSQL and the artifact volume at the same consistency boundary. A database row may
refer to a snapshot, population pool, report, or calibration artifact by URI and content hash.
Redis can normally be rebuilt from durable job state; Qdrant can be rebuilt only if source lore
and embedding configuration are preserved.

Before a schema or promotion change:

1. stop application writes;
2. dump PostgreSQL;
3. archive the artifact volume;
4. record the image tag and migration checksums;
5. restore to an isolated project;
6. verify `/readyz`, authentication, replay hashes, one report, and one character/game workflow.

## Network exposure

Compose publishes API `8000`, PostgreSQL `5432`, Redis `6379`, and Qdrant `6333/6334` on
`127.0.0.1` by default. Do not change bind addresses to `0.0.0.0` without adding a reverse proxy,
TLS, firewall policy, Redis/PostgreSQL network controls, protected Qdrant, secure cookie handling,
and a reviewed origin policy. See [Network and deployment](NETWORK_AND_DEPLOYMENT.md).

## Production image

The Dockerfile uses a Node build stage and a Python runtime stage. The final image:

- runs as the unprivileged `tabletop` user;
- uses a read-only root filesystem in Compose;
- mounts only the artifact volume for writes;
- includes the current persona YAML, migrations, and frontend assets;
- exposes only the application port inside its network;
- uses `/healthz` for container health.

Build and inspect:

```powershell
docker compose --env-file .env -f infra/docker-compose.yml build app
uv build --wheel
uv run python scripts/verify_wheel.py dist/tabletop_dm-2.0.0-py3-none-any.whl
```

## Migration 011 and population routines

Run the normal owner migration lane before starting an image that expects schema 011. This additive
migration preserves existing pools, source members and transition history; it adds binding evidence,
a scoped event foreign key, one embodied identity per body, and source/legacy-transition freeze
guards. Runtime table grants remain unchanged. The wheel verifier and readiness check now require
`011_population_body_binding.sql`. Upgrade and rerun tests use disposable databases.

After a source binds, its old row becomes an immutable import record. Read or change the live member
through the canonical population API/commands; direct legacy state writes intentionally fail.
The canonical body's resources win, so explicitly provision any initial food or equipment. Existing
character cards, pinned personas and minds retain their separate bindings. A source row already
manually linked to an entity cannot silently be rebound.

Routines are opt-in, bounded to 32 bodies per branch, and use the existing world-runner. No extra
service, provider or credential is required. Pause the clock for maintenance; resume with its normal
epoch fence and selected FREEZE/CATCH_UP policy. Routine reconfiguration replaces its managed phase;
disabling cancels managed work before manual activities can take ownership. Monitor the private
population and clock inspections for waiting food, movement, weather or incapacitation. This change
does not apply migrations to a running user database or deploy/restart the live stack automatically.

## Local NPC life plans

Activity due times and resource accounting use the existing clock projection and command ledger.
Keep the application and world runner on the same build when upgrading. Migration 014 remains
the current storage baseline. Existing activity rows gain timing and accounting as they advance.
Use the branch clock endpoint for current progress and the restricted clock event for a phase
that was replaced within one step. Health checks validate service readiness, while a real clock
advance verifies activity behavior.

Optional [daily planning](API_AND_WORKFLOWS.md#daily-goal-planning) shares schema 011 and the same
world-runner. Inspect the private routine's `planner.reason`, `spent`, `day` and `blocked` metadata
when a person changes goals. Needs, rain, injury, exhausted daily quotas and blocked routes can
defer an intention. Supply real food, restore a reachable path or allow the quiet interval to pass;
the policy retries without replacing the routine. Goals reset at simulated midnight, not wall time.
Reconfiguration intentionally replaces the intention menu and counters. Pause the clock before
operator maintenance. No credentials, provider settings, live schema or containers are changed
by adding this opt-in policy.

[Belief/persona motivation](API_AND_WORKFLOWS.md#belief-and-persona-driven-npc-goals) additionally
requires an explicitly associated NPC card, pinned CHARACTER profile and world-scoped mind access
for the configured clock executor. Existing non-user agents need an explicit `mind.read.all`
grant; this does not grant access to private authored cards. The perception projector must catch
up before the next motivated command. Missing evidence projection, profile or authority rejects
the whole command without advancing the clock. Repair the grant/pin or run the projector before
retrying; do not bypass the evidence barrier. Inspect private `motivation` policy/input hash,
source IDs and `planner.reason` (including `BELIEF_AVOIDANCE`/`BELIEVED_DANGER`) to diagnose changes.
Only physical activity is public. Motivation uses schema 011; the current application also requires
snapshot migration 012. The existing worker/credential setup remains current.

## Snapshot metadata and migration 012

Migration 013 must also be applied through the normal owner migration lane before running the
roster recovery/removal changes. It retains the runtime role and forced RLS, but removes stale
runtime-owner delegation after a body's human seat is revoked. The typed removal command pauses
the runtime, advances its epoch and records an explicit `seat_removed` fence; the reference and
RLS authority checks honor that fence while preserving DM control of unowned NPCs. No new worker
or credentials are required. Failed character preparation may retain an uncontrolled body/card/persona binding;
retry the same assignment to finish it. Do not delete its canonical ledger or character history.

Run the normal owner migration lane before starting this application version. Migration 012
replaces projection-only snapshot uniqueness with uniqueness that also includes the artifact ID.
It preserves existing rows, references, append-only protections, runtime grants and RLS. No live
deployment or data reset is needed for isolated test runs; normal deployment still applies the migration.

Contract 2.1 artifacts contain frozen controller and secret entity metadata. Keep the artifact
volume private and back it up with PostgreSQL. SQL rollback can leave an unreferenced content-addressed
file; it does not publish a manifest or partial trial. Legacy 2.0 snapshots remain readable, but
new restoration requires a 2.1 capture rather than copying current metadata into old history.
Whole-campaign checkpoints and abandoned-timeline mind/index restoration remain incomplete.

Travel, daily sleep and social obligations reuse the existing `world-runner` and schema 011;
there is no new service, migration, credential or provider dependency. They are opt-in through
[life plans](API_AND_WORKFLOWS.md#travel-sleep-and-social-obligations). Routine configuration is
a versioned replacement; disabling clears sleeping state and cancels managed activity.

Inspect private routine/activity/obligation state for `PATH_BLOCKED`, `MOVED`, `NO_FOOD`, `DANGER`
or unavailable partners. The planner never teleports a late participant or fabricates food.
Movement uses bounded local routes; large or cross-zone journeys require later navigation work.
Recurring commitments reuse one record, preserve completion/miss counters across restart, and
require cancellation with their current occurrence. Sleep follows simulated time and the clock's
existing FREEZE/CATCH_UP policy. Human wake actions are ordinary authorized body actions; sleeping
policies retain controller budgets. No live upgrade or deployment is performed by adding this code.

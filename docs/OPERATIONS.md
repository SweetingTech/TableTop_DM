# Operations, storage, migrations, and RLS

## Runtime profiles

### Local reference

If `DATABASE_URL`, `REDIS_URL`, and `QDRANT_URL` are absent, the API runs with in-process state
and reports `storage_mode: local_reference`. This is appropriate for deterministic development,
unit tests, and UI work. Restarting the process resets canonical worlds, actors, persona runtime
registries, minds, population lifecycle projections, and telemetry settings. Files already
written to `TTDM_ARTIFACT_ROOT` remain; calibration history and the experiment history catalog
(registered scenarios, jobs, trials, and reports) are rehydrated from those artifacts. Local
reference mode does not turn those files into durable canonical world or population state.

### Durable stack

`infra/docker-compose.yml` defines:

| Service | Role |
| --- | --- |
| `postgres` | Canonical projections, metadata, ledgers, cognition/population/experiment schemas |
| `redis` | RQ experiment queue and coordination |
| `qdrant` | Semantic lore/memory adapter |
| `migrate` | One-shot owner-credential migration and runtime-role provisioning |
| `app` | Flask API and built React client under the least-privilege login |
| `worker` | RQ worker listening on the `experiments` queue |

The app and worker containers run unprivileged with a read-only root filesystem. Only the
artifact volume is writable. PostgreSQL, Redis, Qdrant, and artifacts use separate named
volumes. Every published service port binds to `127.0.0.1` by default; PostgreSQL, Redis,
Qdrant, and the API are not exposed to the LAN by the provided stack.

Start and wait for full readiness:

```powershell
uv run python scripts/manage.py start
```

Use `scripts/start.ps1` or `scripts/start.sh` as thin platform wrappers. `--no-build` reuses the
existing image. `uv run python scripts/manage.py status` shows the Compose services. On first
start, open `/v2`, sign in with `admin` / `admin123`, and replace the bootstrap password when
prompted.

Stop containers while preserving volumes:

```powershell
uv run python scripts/manage.py stop
```

Delete only volumes belonging to the `tabletop-dm-v2` Compose project:

```powershell
uv run python scripts/manage.py stop --volumes
```

Both `start --reset` and `stop --volumes` are destructive for v2 PostgreSQL, Redis, Qdrant, and
artifact volumes. They do not delete arbitrary host paths.

## Configuration

Let the lifecycle manager create `.env`. It generates random PostgreSQL owner/runtime passwords,
a random Redis password, and a compatibility automation token, then restricts the file permissions where
the platform permits. `.env.example` contains deterministic loopback-only values for CI and
disposable tests; the manager does not copy those credentials into a managed stack.

| Variable | Meaning |
| --- | --- |
| `DATABASE_ADMIN_URL` | Owner connection used only by the migration command |
| `DATABASE_URL` | Least-privilege runtime connection used by API/adapters |
| `APP_DATABASE_USER`, `APP_DATABASE_PASSWORD` | Runtime login provisioned by migration |
| `REDIS_URL` | RQ connection, including password when configured |
| `QDRANT_URL` | HTTP endpoint checked by readiness and used by the lore adapter |
| `TTDM_ARTIFACT_ROOT` | Snapshot, population, calibration, and pluggable report/trace artifact root |
| `TTDM_LLM_MODE` | Declared adapter mode; defaults to `mock` and requires an injected provider for model deliberation |
| `TTDM_RNG_SEED` | Deployment seed forwarded to runtime adapters; commands and scenarios still carry explicit seeds |
| `TTDM_OPERATOR_TOKEN` | Operator header secret; generated for the durable stack and required for non-loopback API access |
| `TTDM_TELEMETRY_ENABLED` | Reserved deployment flag; the settings API remains authoritative and defaults off |
| `CORS_ALLOWED_ORIGINS` | Reserved same-origin deployment setting; no cross-origin middleware is installed by default |
| `PORT`, `TTDM_HOST` | HTTP bind configuration used by deployment tooling |

Hosted-model keys are optional. The deterministic and mock paths need none. Do not put secrets
in command proposals, model prompts, event payloads, or committed `.env` files.

## Health behavior

- `/healthz` proves that the HTTP process can answer.
- `/readyz` proves that every configured dependency is usable.
- PostgreSQL readiness requires the latest recorded migration to be exactly
  `002_identity_and_tabletop_workspaces.sql`.
- Redis readiness requires `PING`.
- Qdrant readiness requires its `/readyz` endpoint.

Readiness fails closed with HTTP 503 and per-dependency diagnostics. The Docker health check uses
liveness; the lifecycle manager waits on readiness.

## Migrations

V2 starts from `infra/sql/migrations/001_simulation_kernel.sql`. It creates independent schemas:

- `sim` for worlds, branches, projections, runs, interactions, actors, entities, schedules,
  command log, events, and outbox;
- `artifacts` for content-addressed metadata;
- `persona` for schema versions, blueprint versions, compiled profiles, and assignments;
- `cognition` for minds, observations, beliefs, memories, relationships, runtimes, and traces;
- `population` for world-targeted definitions, pools, cohorts, materialized people, and
  append-only lifecycle transitions;
- `experiments` for scenarios, trials, facts, metrics, jobs, comparisons, calibration, and
  telemetry;
- `infra_meta` for migration versions and checksums.

`002_identity_and_tabletop_workspaces.sql` adds durable users, profiles, sessions, role grants,
characters, hosted games, rosters, and game sessions without rewriting kernel history.

Run migrations explicitly with owner credentials:

```powershell
uv run python infra/migrate.py
```

Check without applying:

```powershell
uv run python infra/migrate.py --check
```

The runner:

- accepts only contiguous `NNN_name.sql` files starting at `001`;
- serializes runners with a PostgreSQL advisory lock;
- records a SHA-256 checksum for every applied file;
- rejects missing-on-disk history or checksum drift;
- applies one file per transaction;
- creates or rotates the non-superuser runtime login and grants membership in `tabletop_app`.

Never edit an applied migration. Add the next numbered file. V1 migrations are deliberately not
part of this history; use a new v2 database.

## Row-level security and least privilege

The owner runs migrations. The API and worker use `tabletop_runtime`, which inherits the
non-login `tabletop_app` role. Public schema access is revoked and runtime grants are limited by
schema and operation.

Forced RLS applies to:

- `sim.branch_projections`, `sim.entities`, `sim.command_log`, and `sim.events`;
- `cognition.mind_states`, observations, beliefs, memories, relationships, runtime assignments,
  and decision traces;
- `experiments.telemetry_captures`.

Each actor-aware transaction sets `app.actor_id`. Policies resolve that ID safely, require
explicit world-scoped capabilities for protected state, restrict trial/canonical mutation, and filter
events by `visible_to`. No actor setting, an unknown actor, or a malformed UUID yields no visible
rows rather than an authorization bypass.

RLS is defense in depth. The command bus still validates the proposal actor, command
capabilities, embodied-entity control, world/branch relationship, and branch kind before invoking
a domain handler. Both the in-memory and PostgreSQL adapters require `action.commit` for a
canonical branch and permit proposal-only authority only on trial branches.

## Append-only and immutable records

Database triggers reject updates or deletes to the command log, event ledger, persona blueprint
versions, compiled persona profiles, observations, memories, decision traces, verifier facts,
and metrics. Telemetry captures reject updates but deliberately allow RLS-scoped deletion for
consent withdrawal and retention expiry. Applications add successor versions or review artifacts
rather than rewriting evidence.

The command repository locks the branch projection and writes these items in one transaction:

1. validated state update and next projection version;
2. resulting state hash in `sim.command_log`;
3. versioned event in `sim.events`;
4. publishable payload in `sim.outbox`.

Any error rolls back all four.

## Data placement and current persistence boundaries

| Data | Primary representation |
| --- | --- |
| Worlds, branches/projections, actors, entities, runs, commands, and events | PostgreSQL in durable mode; memory in reference mode |
| Snapshot payloads | Deterministic gzip files plus PostgreSQL artifact/snapshot metadata |
| Persona schema, blueprint versions, and compiled profiles | PostgreSQL; deterministically rebuilt in reference mode |
| Mind projections and cognition evidence | RLS-scoped PostgreSQL records; `MindStore` hot cache in process |
| Large persona pools | Parquet queried with DuckDB plus PostgreSQL catalog metadata |
| Materialized population and persistent/active/compressed state | PostgreSQL plus append-only versioned transitions |
| Scenario definitions | Immutable filesystem history plus PostgreSQL versions in durable mode |
| Experiment jobs, checkpoints, normalized trial outputs/events, and cohort reports | Immutable filesystem history plus PostgreSQL artifact/job catalogs in durable mode |
| Semantic lore | In-process lexical index or Qdrant adapter |
| Calibration proposals, reviews, and promotions | Immutable JSON artifacts reloaded at boot |
| Human telemetry settings and captures | PostgreSQL in durable mode; memory in reference mode |
| Queue coordination | Redis/RQ |
| React assets | Built into `static/v2`, served at `/static/v2/*`, and included in the image |

`PostgresControlPlane.hydrate` reconstructs every stored world, branch/projection, explicit
world/actor authority set, controlled entity, run, snapshot manifest, command replay record and
basis, and visible event envelope after the authorized bootstrap sync. Persona versions/profiles,
cognition evidence, population pool catalogs and full persistent/active/compressed lifecycle
state plus transition history, and scenario definitions are also reloaded through their domain
repositories. Experiment history reconstructs scenario versions, jobs/checkpoints, normalized
trial outputs with event envelopes, and reports from artifacts; PostgreSQL supplies the durable
catalog when configured. Calibration history is reconstructed from its immutable artifact set.

Terminal experiment jobs and their report/trial inspection views remain available after API
restart. A job last recorded as `RUNNING` is restored as `FAILED` rather than silently repeated,
because the new process cannot prove whether an external side effect completed. Its registered
runner is reattached and the operator may use the bounded retry endpoint. Redis/RQ still provides
queued execution and coordination; queue transport does not replace immutable output history.

Durable replay hydrates `ReplayRecord` values from `sim.command_log`, selects the newest valid
snapshot boundary for each branch, and verifies subsequent records against their committed state
hashes. Snapshot uniqueness includes the command boundary, so an unchanged projection can be
captured before and after a no-delta command without collapsing audit history.

Telemetry settings and captures are PostgreSQL-backed in durable mode. Export/import, selective
delete, and retention purge are explicit API operations; none sends data to an external sink.

Population definitions store an immutable world/branch target. Every materialize, activate, and
deactivate call is checked against that target, and the lifecycle repository restores monotonic
world steps plus append-only transitions. A pool cannot be moved to another active UI world.

Secret entity state remains separate from public projections. Controllers and actors with the
same-world `entity.read.secret` capability may receive authorized secret fields; public entity
lists and grants from unrelated worlds do not expose them. Relationship projections have a
separate immutable causal-change history tied by foreign key to the visible source event in the
same world branch.

## Backups and recovery

For a durable deployment, back up PostgreSQL and the artifact volume together. A database row may
reference a snapshot or report artifact by URI and content hash, so restoring only one side is
incomplete. Parquet pools can be regenerated from their schema/generator versions and seed, but
preserve any pool used as evidence for a report.

Before changing migrations or promotion logic:

1. stop writes;
2. capture a PostgreSQL backup;
3. copy the artifact volume;
4. record the application image/tag and migration checksums;
5. restore into an isolated environment and verify `/readyz` plus replay hashes.

The v1 code can be inspected or run from `v1-behavioral-reference-2026-08-17`, pinned to
`93e02846e4d73097afc65f2dfd684a8a7e49966b`; verification commands and the release-bundle
checksum are in the [Phase 0 behavioral-reference manifest](V1_BEHAVIORAL_REFERENCE.md). There
is no v1 database restoration path inside v2.

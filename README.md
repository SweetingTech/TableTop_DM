# TableTop DM

TableTop DM is a local-first tabletop platform built on a deterministic simulation kernel. It
supports authenticated Administrator, Dungeon Master, and Player workspaces alongside persistent
world state, synthetic personas, population simulation, and isolated scenario evaluation.

Language models may propose dialogue or actions, but they never write canonical state. Typed
commands, world-scoped authorization, deterministic handlers, atomic transactions, and an
append-only ledger decide what actually happened.

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

The initial account is `admin` with password `admin123`. The first sign-in is restricted to the
password-change screen, and the replacement password must be at least 12 characters and not a
common default.

## System layers

| Package | Responsibility |
| --- | --- |
| `identity/` | Accounts, secure password hashing, sessions, profile data, audit records, and global/world role grants |
| `kernel/` | Actors, capabilities, typed commands, state transactions, events, visibility, snapshots, branches, replay, and API composition |
| `domains/tabletop/` | Characters, games, sessions, dialogue, movement, combat, magic, economy, factions, divine effects, quests, and content rules |
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
         -> command/event/outbox append -> optional derived cognition or narration
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
hours. Five failed logins lock an account for 15 minutes. Administrators can reset another
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

- [Simulation-kernel contract](docs/SIMULATION_KERNEL.md)
- [Architecture and invariants](docs/ARCHITECTURE.md)
- [Network and deployment diagram](docs/NETWORK_AND_DEPLOYMENT.md)
- [API and user workflows](docs/API_AND_WORKFLOWS.md)
- [Operations, storage, migrations, and security](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)
- [Repository guidance for coding agents](AGENTS.md)
- [Changelog](CHANGELOG.md)

## Independence and evidence boundary

TableTop DM is independently implemented. It does not import, embed, or depend on MatrAIx. It
adopts general methods such as constrained persona generation, reproducible cohort sampling,
task-specific verification, and population aggregation, then integrates them with its own
persistent deterministic world model.

Synthetic people and simulated player cohorts are tools for exploration, stress testing, and
hypothesis generation. They are not substitutes for evidence from real people.

## License

See [LICENSE](LICENSE).

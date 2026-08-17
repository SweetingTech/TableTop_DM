# TableTop DM v2

TableTop DM is a deterministic simulation kernel with tabletop as its first domain. It keeps
canonical reality, subjective cognition, population-scale sampling, and counterfactual trials
behind explicit contracts instead of letting a model write world state directly.

This is an independent clean-break rebuild. It borrows useful methodology from persona and
evaluation systems, including constrained generation, seeded cohorts, normalized verification,
and cross-trial aggregation, but it does **not** merge, import, or depend on the MatrAIx
repository or runtime.

## What is implemented

| Layer | Responsibility |
| --- | --- |
| `kernel/` | Actors, capabilities, typed commands, atomic state changes, events, visibility, snapshots, trial branches, replay, scheduling, and PostgreSQL adapters |
| `domains/tabletop/` | Dialogue, movement, combat, magic, economy, factions, divine effects, quests, and onboarding commands |
| `persona/` | 80 versioned dimensions in four packs, dependency ordering, constraints, seeded generation, validation, provenance, compilation, and bounded prompts |
| `cognition/` | Perception, observations, beliefs, memory, relationship vectors, reflexes, utility policy, GOAP planning, and typed LLM deliberation |
| `population/` | Parquet persona pools, DuckDB cohort filtering, weighted/stratified sampling, feasibility checks, and statistical/materialized/active lifecycles |
| `experiments/` | Immutable scenarios, isolated trials, resumable jobs, deterministic verifier facts, metrics, aggregation, reports, calibration, and opt-in telemetry |
| `frontend/` | React workspaces for play, world control, personas, populations, scenarios, run inspection, calibration, and settings |

Every mutation follows the same order:

```text
proposal -> schema validation -> capability/entity control -> deterministic handler
         -> atomic state delta -> append-only event/command ledger -> optional narration
```

The model may propose. The kernel decides whether anything happened.

## Quick start

Requirements:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- Docker with Compose v2 for the durable stack

### Local reference mode

This mode needs no database or model key. Canonical worlds, authority, cognition, and population
lifecycle projections are process-local. Snapshot and population files, calibration history, and
the experiment history catalog (scenario versions, jobs, trials, and reports) are written beneath
`artifacts/`; the experiment and calibration views rehydrate from those files after restart.

```powershell
uv sync --frozen
npm --prefix frontend ci
npm --prefix frontend run build
uv run tabletop-dm doctor
uv run tabletop-dm serve
```

Open <http://127.0.0.1:8000/v2/game>. The service starts with a small Eclipse Keep demo world.
`GET /readyz` reports `local_reference` storage when external stores are not configured.

For frontend development, run the API as above and start Vite in another terminal:

```powershell
npm --prefix frontend run dev
```

Vite is available at <http://127.0.0.1:5173/v2/game> and proxies `/api` to port 8000.

### Durable Docker stack

The managed stack builds the frontend and Python image, applies the clean v2 baseline, then
starts PostgreSQL, Redis, Qdrant, the API, and the experiment worker:

```powershell
uv run python scripts/manage.py start
uv run python scripts/manage.py status
```

The manager creates `.env` with random PostgreSQL, Redis, and operator secrets if it is missing;
it never copies the checked-in CI credentials. It also binds every published port to loopback and
waits for dependency-aware readiness. Retrieve the browser/API token at any time with:

```powershell
uv run python scripts/manage.py token
```

Durable boot rehydrates control-plane state, persona records, cognition evidence, population
catalogs and activation state, scenario definitions, calibration artifacts, and consented
telemetry. It also restores command replay records and snapshot bases plus experiment jobs,
normalized trial outputs, and cohort reports from artifacts and PostgreSQL. A job interrupted
while `RUNNING` is restored as failed rather than silently repeated and can be retried explicitly.

Stop without deleting data:

```powershell
uv run python scripts/manage.py stop
```

Reset only this Compose project's volumes:

```powershell
uv run python scripts/manage.py start --reset
```

`--reset` is destructive. The equivalent Make targets are `make up`, `make status`, `make down`,
and `make purge`.

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

## Web workspaces

- **Game Console** shows canonical entities at their public grid coordinates, displays visible
  events, and submits dialogue or typed `/move`, `/attack`, and `/cast` proposals.
- **Control Plane** creates worlds, world-scoped actors and embodied entities, runs, canonical
  snapshots, and isolated trial branches.
- **Persona Studio** fixes selected dimensions, generates and validates identities, and previews
  compiled behavior.
- **Population Studio** creates world-scoped Parquet pools, samples reproducible cohorts, and
  materializes or activates only pools owned by the selected world.
- **Scenario Lab** runs registered immutable scenario definitions, including simulated-player
  onboarding and generic snapshot-based experiments.
- **Run Inspector** examines jobs, trials, metrics, branches, events, and replay state.
- **Calibration** compares synthetic metrics with versioned human evidence, records an explicit
  review, and can promote an approved immutable version into the deployable registry. Runtime
  assignment remains a separate operator action.
- **Settings** configures a session-scoped operator token and explicit local telemetry consent.

The UI displays whether it is connected to the live kernel or showing demo fallback fixtures.
Fallback data is for interface inspection; mutations require the live API.

## API example

Command contracts are discoverable rather than duplicated in clients:

```powershell
curl.exe http://127.0.0.1:8000/api/v2/commands/contracts
curl.exe -X POST http://127.0.0.1:8000/api/v2/commands `
  -H "Content-Type: application/json" `
  -d '{"command_type":"tabletop.console.submit","parameters":{"text":"I greet the gatekeeper."},"idempotency_key":"readme-dialogue-1"}'
```

The demo world, branch, run, and actor IDs are defaulted when omitted. Real callers should send
all IDs and reuse an idempotency key only when retrying the same command. When
`TTDM_OPERATOR_TOKEN` is configured, add `X-TTDM-Operator-Token` to every non-health v2 API
request. The browser stores that token in session storage, never local storage.

See [API and user workflows](docs/API_AND_WORKFLOWS.md) for resource groups and end-to-end flows.

## Verification

Fast function- and contract-level verification:

```powershell
uv run python scripts/test.py fast
```

The repository also has PostgreSQL/Redis integration tests, React tests, production image
builds, and Playwright journeys over every workspace. See [Testing](docs/TESTING.md) for the
exact lanes and prerequisites.

## Architecture and operations

- [V2 design contract](docs/V2_SIMULATION_KERNEL.md)
- [Phase 0 behavioral-reference manifest](docs/V1_BEHAVIORAL_REFERENCE.md)
- [Architecture and invariants](docs/ARCHITECTURE.md)
- [API and user workflows](docs/API_AND_WORKFLOWS.md)
- [Operations, storage, migrations, and RLS](docs/OPERATIONS.md)
- [Testing](docs/TESTING.md)

## Clean-break boundary

V2 intentionally does not migrate v1 schemas or save data. The old application is preserved at
the Git tag `v1-behavioral-reference-2026-08-17`, pinned to commit
`93e02846e4d73097afc65f2dfd684a8a7e49966b`. Its tests, fixtures, release evidence, and v1.0.0
bundle remain retrievable as recorded in the
[Phase 0 behavioral-reference manifest](docs/V1_BEHAVIORAL_REFERENCE.md). To inspect it without
changing this checkout:

```powershell
git worktree add ..\TableTop_DM-v1 v1-behavioral-reference-2026-08-17
```

There is one fresh-install migration, `001_simulation_kernel.sql`. Do not point v2 at a v1
database and expect an in-place upgrade.

## License

See [LICENSE](LICENSE).

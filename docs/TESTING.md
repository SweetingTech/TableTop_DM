# Testing

Verification is split into deterministic function/contract checks, real durable-boundary tests,
and user-level browser journeys. The default model mode is `mock`; hosted model credentials are
not required.

## Install dependencies

```powershell
uv sync --frozen
npm --prefix frontend ci
uv run playwright install chromium
```

## Test lanes

| Lane | Command | Evidence |
| --- | --- | --- |
| Python lint | `uv run ruff check .` | imports and correctness rules |
| Python format | `uv run ruff format --check .` | deterministic formatting |
| Python types | `uv run mypy kernel persona cognition population experiments domains identity infra main.py` | typed boundaries |
| Unit | `uv run pytest -m unit` | pure functions, policies, handlers, and API composition |
| Contract | `uv run pytest -m contracts` | migration, Compose, manager, packaging, and CI invariants |
| Frontend lint | `npm --prefix frontend run lint` | TypeScript/React rules |
| Frontend unit | `npm --prefix frontend run test` | role routing, APIs, components, and user interactions |
| Frontend build | `npm --prefix frontend run build` | TypeScript compilation and production assets |
| Integration | `$env:TTDM_INTEGRATION='1'; uv run pytest -m integration -v` | PostgreSQL/RLS/restart/Redis boundaries |
| Browser | `uv run pytest -m e2e tests/e2e -v` | live authenticated workflows in Chromium |
| Wheel | `uv build --wheel` then `scripts/verify_wheel.py` | installed schema, migrations, and SPA assets |

The cross-platform dispatcher runs the fast lane:

```powershell
uv run python scripts/test.py fast
```

Equivalent wrappers are `scripts/test.ps1` and `scripts/test.sh`. Supported suites are `fast`,
`unit`, `contracts`, `integration`, `e2e`, and `all`. `all` does not start or destroy Docker
services; lifecycle remains explicit.

## Function-level coverage

Unit tests cover:

- password policy, login failure/lockout, session rotation, account lifecycle, final-admin
  protection, and global/world roles;
- character build/generate/import, ownership, game hosting, eligible rosters, co-DM/player
  membership, session scheduling, and private DM notes;
- copy-on-write command execution, rollback, idempotency, state hashes, deny-by-default
  capabilities, world/run/branch lineage, and entity control;
- movement/collision, seeded combat, magic resources, economic conservation, reputation, divine
  effects, quests, dialogue, and onboarding;
- snapshot hashes, branch isolation, promotion, and replay;
- persona dependencies, fixed dimensions, constraints, provenance, lineage, compilation, and
  prompt budgets;
- perception, divergent beliefs, memory, relationships, reflex/utility/planner/model selection,
  runtime tier ceilings, fallback, and no-input-mutation guarantees;
- Parquet streaming, DuckDB filtering, weighted/stratified sampling, feasibility, tolerance, and
  population activation transitions;
- scenario lifecycle, typed branch execution, verifier evidence, normalized metrics, reports,
  checkpoints, cancel/retry, restart hydration, calibration review/promotion, and telemetry
  consent/retention.

Stochastic tests assert seed-based reproduction. Model-tier tests use typed fakes and ensure the
chosen action remains inside the supplied allowlist.

## Integration environment

Integration tests require PostgreSQL and Redis; Qdrant is included for readiness tests. Start
only dependencies with isolated disposable credentials:

```powershell
docker compose --env-file .env.example -f infra/docker-compose.yml up -d postgres redis qdrant
$env:TTDM_INTEGRATION = '1'
$env:TTDM_TEST_DATABASE_ADMIN_URL = 'postgresql://postgres:postgres_dev_only@127.0.0.1:5432/postgres'
$env:TTDM_TEST_REDIS_URL = 'redis://:redis_dev_only@127.0.0.1:6379/15'
uv run pytest -m integration -v
```

The fixture creates a unique database and least-privilege runtime role, applies migrations, and
drops both afterward. It does not reuse the application database.

Integration assertions include:

- fresh apply, repeat apply, ordered migration state, and checksum-drift rejection;
- identity bootstrap, forced password change, session cookies, password reset, role sync, portal
  ownership, restart hydration, and private field isolation;
- composite world/branch/run foreign keys and branch-scoped entity IDs;
- forced RLS with absent, valid, cross-world, and malformed actor context;
- append-only enforcement even for table-owner attempts;
- projection/command/event/outbox atomicity, durable idempotency, entity-secret redaction, and
  rollback;
- replay bases and multiple same-state snapshot boundaries;
- persona lineage, cognition/relationship/runtime-assignment persistence, population lifecycle,
  scenario/job/trial/report restoration, telemetry deletion/retention, and Redis worker retry.

Stop disposable dependencies:

```powershell
docker compose --env-file .env.example -f infra/docker-compose.yml down --volumes --remove-orphans
```

## Browser journeys

Start the full stack:

```powershell
uv run python scripts/manage.py start
$env:TTDM_BASE_URL = 'http://127.0.0.1:8000'
uv run pytest -m e2e tests/e2e -v
```

Playwright verifies:

- a fresh browser can sign in with the bootstrap admin and must change the password;
- all role-appropriate routes render and unauthorized workspaces are inaccessible;
- account creation, global/world role assignment, password reset, and profile changes;
- Player character build, deterministic generation, template import, statistics, and status;
- DM game creation, roster/character assignment, status, and session management;
- Control Plane world -> actor -> entity -> run -> snapshot -> branch flow;
- typed dialogue and movement update canonical state and visible events;
- persona, population, scenario, run inspection, and calibration review/promotion flows;
- completed jobs and detailed ledgers remain visible after a real application restart;
- desktop/mobile layouts have no document overflow or unexpected console errors.

Screenshots, traces, and videos are retained under `test-results-e2e/` when configured or on
failure. Those generated results are ignored by Git.

## Packaging and image verification

The wheel must contain all runtime data, not only Python modules:

```powershell
uv build --wheel
uv run python scripts/verify_wheel.py dist/tabletop_dm-2.0.0-py3-none-any.whl
```

The verifier extracts the wheel and checks the 80-dimension schema, ordered migrations,
SPA index, and current hashed assets. Always remove stale local `build/` output before diagnosing
a packaging mismatch.

The production image gate builds from a clean context, runs as an unprivileged user, and serves
JavaScript/CSS assets with their correct MIME types rather than the SPA fallback document.

## CI mapping

- `.github/workflows/ci.yml`: Python quality/types, unit/contract, frontend, integration, and
  production-image gates.
- `.github/workflows/e2e.yml`: full Compose stack and Playwright user journeys.
- `.github/workflows/cd.yml`: tagged image build and GHCR publication.

When a failure crosses layers, preserve the earliest deterministic evidence: account/actor role
scope, request contract, idempotency key, seed, state hash, event/trace IDs, migration checksum,
and failing artifact or browser trace. Never preserve credentials or private content in logs.

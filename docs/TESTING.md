# Testing

The verification strategy separates fast function-level evidence from durable-boundary and
user-level evidence. The default model mode is deterministic `mock`; tests do not need hosted
model credentials. The v1 oracle is independently pinned and retrievable as documented in the
[Phase 0 behavioral-reference manifest](V1_BEHAVIORAL_REFERENCE.md); no v2 lane imports or runs
v1 code implicitly.

## Install test dependencies

```powershell
uv sync --frozen
npm --prefix frontend ci
```

Install Chromium once before local browser tests:

```powershell
uv run playwright install chromium
```

## Lanes

| Lane | Command | What it proves |
| --- | --- | --- |
| Python lint | `uv run ruff check .` | imports, common correctness rules, and repository style |
| Python format | `uv run ruff format --check .` | deterministic formatting |
| Python types | `uv run mypy kernel persona cognition population experiments domains main.py` | checked public and internal contracts |
| Unit | `uv run pytest -m unit` | pure kernel/domain/persona/cognition/population/experiment functions |
| Contract | `uv run pytest -m contracts` | migration, Compose, environment, Dockerfile, and CI invariants |
| Frontend lint | `npm --prefix frontend run lint` | TypeScript/React lint rules |
| Frontend unit | `npm --prefix frontend run test` | component behavior and mocked user journeys |
| Frontend build | `npm --prefix frontend run build` | TypeScript compilation and production bundle |
| Integration | `$env:TTDM_INTEGRATION='1'; uv run pytest -m integration -v` | clean PostgreSQL boot, checksums, RLS, durable domain repositories, commands, telemetry, and Redis worker |
| Browser | `uv run pytest -m e2e tests/e2e -v` | real browser journeys against a ready full stack |

Run the complete fast lane through the cross-platform dispatcher:

```powershell
uv run python scripts/test.py fast
```

Equivalent wrappers:

```powershell
.\scripts\test.ps1 -Suite fast
```

```sh
./scripts/test.sh fast
```

`scripts/test.py` accepts `fast`, `unit`, `contracts`, `integration`, `e2e`, and `all`. `fast`
runs Ruff lint/format, `pytest -m "unit or contracts"`, frontend lint/Vitest, and the production
frontend build. `all` adds integration and browser lanes but deliberately does not start or
destroy services. Mypy remains the explicit command in the lane table and CI rather than an
implicit side effect of `fast`.

## Function-level coverage

Unit tests exercise these failure and determinism boundaries directly:

- atomic copy-on-write commit and rollback;
- idempotent command receipts and stable state hashes;
- deny-by-default capabilities, actor identity, branch kind, and entity control;
- tabletop movement/collision, seeded combat, magic resources, economic conservation,
  reputation, divine effects, quests, dialogue, and onboarding;
- snapshot content hashes, trial isolation, explicit canonical promotion, and replay;
- persona dependency order, fixed dimensions, invalid constraints, provenance, lineage,
  compilation, and prompt budgets;
- perception scope, divergent beliefs, memory, relationship vectors, reflex/utility/planner/LLM
  selection, fallback, no-input-mutation guarantees, and immutable source-event causal history;
- Parquet streaming, deterministic weighted/stratified cohorts, feasibility, statistical
  tolerance, and activation transitions;
- immutable scenarios, trial lifecycle, verifier evidence, normalized metrics, aggregation,
  generic typed branch execution, event-envelope retention, job/trial/report restart hydration,
  interrupted-job recovery, resumable/cancellable jobs, separate calibration review/promotion,
  and telemetry
  consent/redaction/export/import/retention;
- API aliases and world-scoped lifecycle rejection for populations, two-step cognition proposals
  and subjective evidence, Control Plane creation payloads, canonical map coordinates, and
  production `/static/v2` asset delivery without SPA-fallback MIME corruption.

Tests that use stochastic behavior assert seed-based reproduction. Tests of model escalation use
typed fakes and verify the returned action remains inside the allowed set.

## Integration prerequisites and isolation

Integration tests require reachable PostgreSQL and Redis. Start only the dependencies:

```powershell
docker compose --env-file .env.example -f infra/docker-compose.yml up -d postgres redis qdrant
$env:TTDM_INTEGRATION = '1'
$env:TTDM_TEST_DATABASE_ADMIN_URL = 'postgresql://postgres:postgres_dev_only@127.0.0.1:5432/postgres'
$env:TTDM_TEST_REDIS_URL = 'redis://:redis_dev_only@127.0.0.1:6379/15'
uv run pytest -m integration -v
```

The fixture creates a unique database and least-privilege runtime role for the process, applies
the baseline, and drops both afterward. It does not reuse the application database. The lane
verifies:

- fresh apply, repeat apply, checksum drift rejection, and schema constraints;
- cross-world composite foreign-key rejection and branch-scoped entity identity;
- forced RLS with no, valid, and malformed actor context;
- append-only triggers even when the table owner attempts mutation;
- durable projection/command/event/outbox atomicity, authorization, rollback, idempotency, and
  restart/reload behavior, including replay records and same-state snapshot boundaries;
- persona schema/version and compiled-profile persistence, actor-scoped cognition evidence,
  relationship accumulation/causality, world-scoped population pool/full-lifecycle reload,
  experiment job/trial/report inspection after restart, and durable telemetry
  selection/deletion/retention;
- Redis/RQ worker execution.

Stop and remove the dependency volumes when finished:

```powershell
docker compose --env-file .env.example -f infra/docker-compose.yml down --volumes --remove-orphans
```

## User-level browser journeys

Start the complete application first:

```powershell
uv run python scripts/manage.py start
```

If `TTDM_OPERATOR_TOKEN` is set in the stack, export the same value in the test shell. Then run:

```powershell
$env:TTDM_BASE_URL = 'http://127.0.0.1:8000'
$env:TTDM_OPERATOR_TOKEN = '<same operator token>'
uv run pytest -m e2e tests/e2e -v
```

The preflight requires `/healthz`, `/readyz`, and `/v2`; CI fails rather than silently skipping
an unavailable application. Playwright verifies:

- `/v2` redirects to the URL-addressable Game Console;
- all eight workspaces render and navigate by URL;
- an operator can create a world, world-scoped actor, controlled entity, run, canonical snapshot,
  and isolated trial branch;
- typed dialogue and `/move` proposals commit, reload, and update the public map position;
- a world-scoped population can be generated and sampled;
- a registered scenario completes, its raw event ledger renders, and its run can be inspected;
- calibration requires review before separate registry promotion;
- human telemetry stays off until explicit opt-in and can be disabled again;
- page errors and unexpected browser-console errors fail the test.

Screenshots, traces, and video are retained on failure under `test-results-e2e/`.

## Full local gate

With dependencies and the app already running:

```powershell
uv run python scripts/test.py all
```

`all` runs the fast, integration, and browser lanes. It intentionally does not start or destroy
Docker services, so lifecycle remains explicit.

## CI mapping

- `.github/workflows/ci.yml` runs quality, unit/contract, frontend, isolated integration, and
  production-image jobs.
- `.github/workflows/e2e.yml` builds the full stack and runs Playwright journeys.
- `.github/workflows/cd.yml` builds and publishes tagged images to GHCR.

When a failure crosses layers, preserve the earliest deterministic evidence: request payload,
seed, actor/capability set, command contract version, state hash, event IDs, decision trace, and
the failing artifact or browser trace.

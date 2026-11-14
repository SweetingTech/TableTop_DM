# Testing

Generated-dialogue tests use a local OpenAI-compatible HTTP fixture, never a real provider/key.
They exercise the actual API/runner, multiple turns, sanitized subjective input, unknown sources,
metafiction/extra-field rejection, outage fallback, immutable retries and separate-worker/restart
provenance. A live model smoke test requires the operator's later provider configuration; fixture
tests do not establish a particular model's conversational quality or semantic truthfulness.

Tactical tests cover one-attack guard consumption, no stacking, fixed spell costs/effects, caller
power/cost rejection, live range/sight/zone/resource checks, resource rollback and idempotency,
learned guard choices through a restarted worker, 009→010/repeat migration, new option/source
guards, and retained synthetic exclusion. Browser journeys use the built console for guard/bolt,
autonomous healing and generated speech, then take control. No new screenshot artifacts are committed.

Speech/combat tests demonstrate learned reply intent/volume, basic melee and withdrawal choices
through the actual runner, history-free persona/card differences, no unprovoked/hidden targets,
and no self-reply loop. Durable tests cover equal-timestamp canonical ordering across restart,
009 clean/008-upgrade/repeat apply, evidence rollback, idempotency, stale queued attacks after
takeover, forced RLS, append-only privileges/triggers, source/option/payload/composite-FK guards,
and synthetic exclusion. Legacy movement tests verify unchanged profile hash compatibility.
The isolated speech/combat browser journey records four demonstrations through the built console,
hands control to the real runner, and verifies matching autonomous replies or attacks and takeover.
The scene refresh regression also covers a controller advancing while a reload unmounts its panel.
Review regressions cover sound-only witnesses, independently invisible combat participants, frozen
masks after visibility changes, and 90 equal-timestamp turns with a reply below the old UUID cutoff.
Durable authorization also forces a one-world actor ahead of the established bootstrap identity,
verifying synchronization preserves that identity, rejects its revocation and retains scoped RLS.

Movement behavior tests demonstrate manual choices changing actual runner movement, persona and
authored-card fallback, comparable-layout filtering, foreign scope exclusion, and rejection of
automation/advice as human evidence. Durable tests cover migration 007→008, atomic evidence/action
rollback, idempotency, source guards, forced RLS, append-only privilege/trigger checks, and profiles
surviving application recreation. `test_player_behavior_isolated.py` demonstrates five human moves
through the built console, then a matching autonomous move without training on that move.

Controller/runner coverage includes explicit leave/pause/takeover, missing/stale human epochs,
captured old agent authority, two-worker idempotency, atomic canonical action and step budget,
paused-run and invalid-action handling, private RLS/grant revocation, handoff rollback, migration
006→007, and actual `main.py runner` process restart without a player session. Mixed-world tests
verify unowned NPC witnesses receive observations while the execution agent stays body-scoped.
Controller changes must leave character fiction/evidence unchanged.

The browser journey `tests/e2e/test_controller_runner_isolated.py` exercises Let character act →
bounded autonomous movement → budget pause → Take control → human movement, then repeats handoff
on mobile. It verifies page identity, meaningful content, no page errors, no horizontal overflow,
and desktop/mobile captures. No Browser plugin is available in this environment; the existing
pytest/Chromium Playwright workflow is used. Generated screenshots stay outside the repository.

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

Character-history/binding tests preserve existing card hashes (including Unicode), archive only
authored changes, pin running context across edits, and explicitly adopt a successor without
resetting nonempty memories or human runtime selection. Forbidden playtester profiles, foreign
bodies/runs/revisions, stale replacements, and broad scene inspection without mind access fail
closed. Durable tests cover migration-004 upgrade/backfill, RLS, grants, immutable triggers,
composite foreign keys, concurrent replacement, atomic neutral-mind rollback, app recreation, and
two actual API processes reading the same pinned identity. The isolated Chromium journey edits
a card through the built SPA, checks history/pinning, explicitly rebinds, and verifies movement,
private-feed separation, reload, keyboard use, and mobile overflow.

Basic character-action tests cover deterministic typed movement attempts, required world
capabilities, canonical versus trial authority, inspect-only access, perceived incapacity, and
no private IDs in labels. Hidden obstacles leave the catalog/evidence hash unchanged; the kernel
rejects blocked attempts without writes and commits a valid retried action once. Durable context
reads retain the same versioned catalog after app recreation.

Scene-refresh regressions cover delayed subjective projection, scoped/unknown receipt rejection,
unperceived actions, cancellation, eight-second timeout, stale responses, source-event deduplication,
world/viewpoint resets, keyboard focus, and read-only retry after acceptance. The durable test
projects an event externally twice, reads it through a stale API cache, and recreates the app.
`tests/e2e/test_scene_refresh_isolated.py` exercises a real cookie-authorized built SPA with delayed
projection, automatic movement/position refresh, dialogue, reload, and desktop/mobile overflow.

Authored-card tests cover bounded typed fiction, reserved sheet-key rejection, unchanged-card
hash stability across wounds/binding, content edits, legacy hydration, and durable identity/hash
restart round trips. Frontend tests preserve multiline editing and serialize separate claims;
the isolated character-identity browser journey exercises real build/edit/import API calls.

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

Persona-purpose tests also verify excluded player/interface traits cannot reenter character
prompts, historical playtester hashes/UUIDs stay stable, character profiles survive repository
reload, mismatched blueprint/profile purposes roll back, and upgrade from migration 003 preserves
legacy rows. The integration lane creates and drops a separate disposable database for that
upgrade; it never downgrades the application database.

Character-context tests inject foreign-world, abandoned-branch, foreign-observer, operator-tagged,
and ungranted evidence, plus forged belief/memory summaries. None may become model-facing facts.
Frozen grants remain usable after the observer moves. Context hashes ignore wall-clock generation
time, and an actual API process restart must preserve context evidence. API tests also verify
viewpoint authorization, evaluation role gating, and rejection of caller-authored character decisions.
Current visual context must honor blindness/acuity while retaining self and previous experience;
distinct belief subjects must retain consistent context-local references without kernel IDs.

Trusted-proposal tests verify exact pinned inputs, forbidden caller policy fields, actual body
control, a retryable subjective-projection barrier, and absence of hidden/operator/abandoned-branch
facts in live policy inputs. Advice leaves canonical state and human runtime assignments unchanged;
only a separate normal kernel submission applies it. Disposable PostgreSQL tests cover migration
005→006, forced RLS, append-only grants/triggers, receipt/binding/trace constraints, concurrent
idempotency, atomic rollback, fresh cross-process state and real API process restart. Isolated
browser tests request advice with the ordinary session cookie and exercise normal command refresh.

Compiled-profile retries reject changes to every persisted profile field and leave the original
usable after rollback. Browser authorization tests reject cross-site, opaque, malformed, and
wrong-port login origins without issuing a cookie, while preserving same-origin login.

Sensory regressions cover zero, invalid, non-finite, and sub-precision acuity, mixed modalities,
and stronger indirect portal paths under reversed ordering. Reference and durable API tests
both deny foreign-world and uncontrolled-mind reads while allowing a controller's own mind.

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

Deferred roster tests verify immediate clearing of another user's choices/errors, disabled saves
during pending lookups and player/co-DM switches, and rejection of obsolete responses after a
newer lookup completes. Browser verification delays a real character lookup before inviting and
updating the selected member.

The isolated regression is `tests/e2e/test_roster_assignment_isolated.py`. The committed
[A1 verification manifest](verification/a1-roster-review-2026-11-12/manifest.json) links actual
fast/type/integration/browser/build reports, their SHA-256 hashes, and the tested source revision.
Screenshots stay local and are not part of the repository evidence bundle.

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

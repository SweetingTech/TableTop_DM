# Testing

The complete PostgreSQL/RLS/worker integration CI job has a 35-minute limit to accommodate
the full suite under runner load. Every integration test still runs; a timeout is incomplete
verification and must not be reported as a pass.

Roster recovery tests cover missing/finished runs, preparation/final-publication failures,
retry deduplication, reassignment, shared seats, removal, epoch fencing and rejoining without
losing the body or pinned binding. The durable lane verifies seat/control rollback, restarted
retry, runtime-owner forced-RLS denial and paused runners after removal. Migration013 is tested
on a clean install and012 upgrade, transaction rollback, repeat application and least-privilege
function grants. These are A2/A3 checks; full A2–A8 acceptance also requires the two-client UI
journey and restart described in the campaign checklist.

Console regressions cover same-version projection, cancelled/out-of-order reads, monotonic
versions, reconnect, denied-access clearing, pinned bodies, draft/focus preservation and stale
read labels. Readiness tests cover delayed other-body evidence, stored confidence precision and
rejection of changed source/body/payload/time/confidence. Map tests cover translated/negative
coordinates, unknown/out-of-bounds positions, player configuration denial and hidden-zone/model
context exclusion. `tests/e2e/test_human_play_closeout.py` uses isolated PostgreSQL, two real
cookie-authenticated Chromium clients, the built SPA and a real projector. It exercises DM
invitations, movement, dialogue, attacks, polling health/position, more than four tokens,
viewpoint/draft isolation, unsupported-command guidance without a POST or draft loss, offline
recovery and app restart at the same URL. Parser/API regressions also reject unknown slash
commands before any network request. Run it with
`TTDM_INTEGRATION=1` and the integration database/Redis settings in the existing browser lane.

Timed-effect tests cover mid-step condition/blessing expiry, permanent-source preservation,
independent stacks/capacity/retries, world authority, rejected caller expiry/death values, legacy
blessing anchoring and split-versus-whole weather/effect/readiness boundaries. Manual activities,
coarse routines, life plans, goal planning and social attendance cannot accrue blocked work;
missing-health bodies remain unavailable. Run `uv run python -m pytest
tests/unit/kernel/test_timed_effects_api.py tests/unit/population`.
The integration lane for `tests/integration/test_timed_effects.py` verifies reference/durable
parity, restart/late retries/replay, rollback after an injected intermediate-boundary failure and
restarted autonomous recovery. `tests/e2e/test_timed_effects_isolated.py` exercises the built live
sheet, incapacity/readiness rejection, expiry/recovery, unchanged authored card and offscreen work.

Shared-clock action tests exercise physical durations, body-owned movement speed, non-overridable
costs, retry/no-write rejection, actual concurrent reference submissions, finite guard expiry,
self-only scene readiness and controller wait/race/resume. Run `uv run python -m pytest
tests/unit/kernel/test_action_time_api.py tests/unit/kernel/test_world_time.py`.
The integration lane for `tests/integration/test_action_time.py` compares reference/durable state,
restarts and retries real resource effects, verifies ledger replay, races separate durable
transactions and resumes a restarted autonomous runner without wait-budget loss.
The actual built-SPA `tests/e2e/test_action_time_isolated.py` journey guards, rejects premature
movement without a new event, advances the shared clock and offscreen gardening, then moves and
observes the refreshed scene and expired guard.
Camera regressions cover ready/busy, sleeping, stunned and dead bodies, unchanged resources and
reservations, controlled-entity authorization, restart and idempotent metadata updates.

Live-sheet frontend tests cover canonical values, denied refresh without authored fallback,
cancelled out-of-order reads, explicit unbound editing, in-flight deduplication and invalid typed
responses. Run `npm --prefix frontend run test -- --run src/test/CharacterLiveState.test.tsx`.
The built-SPA journey `tests/e2e/test_character_live_sheet_isolated.py` exercises actual healing,
automatic resource refresh, unchanged card/draft, bound edit rejection, unbound setup, real role
revocation, focus retention and desktop/mobile overflow against its own ready reference app.

Bound-resource ownership tests reject all five physical fields and world retargeting for owners
and administrators, including mixed identity requests, without card or canonical writes. They
preserve identity/unbound edits and PATCH-null behavior. Durable tests repeat after restart and
compare card rows plus projection/command/event/outbox marks. Run
`uv run python -m pytest tests/unit/kernel/test_character_resource_ownership.py` and the integration
lane for `tests/integration/test_character_resource_ownership.py`.

Character live-state tests cover actual healing and resource consumption, unchanged authored
card/version, explicit unbound source, missing/cross-world/trial projection rejection, owner/world
authorization, secret/unknown-field exclusion and no-store errors. Durable tests verify unchanged
ledger/projection counts on reads, restart equality and current role revocation. Run
`uv run python -m pytest tests/unit/kernel/test_character_live_state.py` and the integration lane
for `tests/integration/test_character_live_state.py`.

Body-capability regressions exercise zero HP, defeat, mixed-case conditions, dead flags/status,
movement/speech/guard parity, sleeping policy suspension, successful and failed human combat wakeup,
dead-target healing and self-only scene status. Durable tests verify no-write rejection, mana/wake
atomicity, retry/restart and ledger replay. Use `uv run python -m pytest
tests/unit/tabletop/test_body_capability.py` and the integration lane for
`tests/integration/test_body_capability.py`.
Actual stand-in regressions repeat incapacitated polls, inject a proposal-to-commit stun race,
verify unchanged failure/step budgets and resume successfully after recovery.

Generic cognition CHARACTER-mode regressions verify shared scoped-route receipts, no canonical
mutation, strict rejection of caller context/actions/seeds/identity/provider overrides, exact
control/run-lineage authorization and privileged evaluation separation. Durable tests repeat the
same receipt through both routes after restart. Run `uv run python -m pytest
tests/unit/kernel/test_cognition_character_entrypoint.py` and the integration lane for
`tests/integration/test_cognition_character_entrypoint.py`.

Action-randomness regressions cover caller-seed independence, logical sequence allocation,
failure rollback, concurrent commits, original retry receipts and private physical masks. Durable
tests compare reference outcomes, restart retries, real concurrent repository transactions and
ledger replay. Run `uv run python -m pytest tests/unit/kernel/test_action_randomness.py` and, with
the configured disposable integration stack, `uv run python -m pytest -m integration
tests/integration/test_action_randomness.py tests/integration/test_action_rules.py`.

Action-rule tests reject caller-selected dice/bonuses/power/cost without projection, command,
event or outbox writes. They cover owned weapon reach, hidden/walled targets, conditions,
learned spell privacy/candidates, initial card validation and stale-card resource preservation.
Equipment regressions cover final-versus-retained copies, atomic trade unequip, legacy stale
loadouts, and scene/context/retry/replay after durable restart.
Durable regressions compare human and separate-runner fixed spell effects, restart retries and
committed legacy-schema receipts. Built-SPA journeys cover both spell aliases, rejected legacy
syntax, current health after an action and mobile overflow. Logical action-seed allocation and
full combat lifecycle acceptance remain separate checklist items.

Knowledge-boundary regressions cover old learned facts beyond the recent experience window,
masked/hidden/operator/other-world/other-branch sources, pinned starting claims after card edits,
scene inspection without mind access, deity/operator knowledge separation, pending projection
and idempotent recovery. Provider fixtures retrieve older grounded testimony without kernel IDs;
durable cases exercise restart, actor-scoped reads and trial testimony isolation. Kernel tests
ensure non-sensory records never invoke a physical emission builder or audience resolver. These
tests do not establish a complete campaign rewind or a model's general semantic truthfulness.

Relationship/snapshot repair tests cover frozen physical classification, rejected fabricated
promise/rescue reactions, masked raw-event RLS, immutable retries after later updates, current
vectors across independent API processes, nested trial-only bodies and historical secrets,
metadata-distinct snapshot IDs with equal projection hashes, tamper rejection, exact base snapshot
lineage after restart/replay, and transaction rollback without partial in-memory publication.
Migration 012 is exercised on clean installs and upgrades from 011 with a retained legacy artifact.
Legacy projection-only artifacts stay readable and fail closed for new entity restoration.
Generic scenario regressions execute populated cohorts through the durable API, verify frozen
entity metadata and distinct trial identities, and check replay/retry after restart. Terminal
trial upserts preserve valid timestamps and record the original scenario failure.

World-time tests cover epoch/step/executor fencing, pause/resume and manual boundaries, FREEZE and
bounded CATCH_UP, deterministic ordering/replay, trial/world isolation, empty-viewer progression,
rain boundaries and partial work, rest/cancel/movement/incapacity, and inspected activity privacy.
Durable tests run two actual `main.py world-runner` processes, restart without browser presence,
race stale applications, revoke runtime grants, exercise RLS and roll back clock/effects/weather
after ledger insertion fails. Character/world runners are tested on one branch. The built-SPA
journey shows partial waiting work and resumed work on return at desktop/mobile sizes. Browser
plugin is not available; the repository's regular Playwright/Chromium lane is used.

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
SPA index, and current hashed assets. These checks remain active with `PYTHONOPTIMIZE` enabled;
unit regressions run broken package fixtures in optimized subprocesses. Build from a fresh
temporary source copy when diagnosing a packaging mismatch to avoid stale local `build/` output.

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

Population routine coverage is in `tests/unit/population/test_runtime.py`,
`tests/unit/kernel/test_population_runtime_api.py`, `tests/integration/test_population_runtime.py`
and `tests/e2e/test_population_routines_isolated.py`. Run the repository fast/types gates, the full
integration lane, frontend lint/tests/build and the population/world-time browser journeys.
The browser journey checks the built SPA at desktop/mobile sizes; when no browser connector is
available, use the repository's Playwright/Chromium lane.

The durable population lane exercises clean schema 011, upgrade from 010 with an existing member,
idempotent migration rerun, binding/source validation, SQL freeze guards and runtime grants,
cross-world/RLS denial, injected rollback, fresh API reads, two real world-runner processes and a
subsequent worker restart. The reference lane compares coarse/split progression, including hunger
during long rain waits, partial-work lifecycle continuity and trial isolation. Build a clean wheel
and run its verifier because packaged migration expectations changed. Never point these tests at
the user's live application database.

Life-plan coverage is in `tests/unit/population/test_life.py`,
`tests/integration/test_population_life.py` and `tests/e2e/test_population_life_isolated.py`.
Reference tests compare coarse/split travel, sleep and attendance; cover blocked routing, saved work,
repeating/overlapping commitments, hunger, injury, midnight/day cycles and unmanaged participants;
and verify sleeping character policies preserve budgets while human actions can wake bodies.
Durable tests inject rollback after movement, race two actual world-runner processes, restart
mid-commute, verify recurring meetings, replay, world/role denial and scene/context privacy, and
reject a captured character policy after the clock puts its body to sleep. They
also check sleeping sensory exclusion, immutable old audiences and immediate injury wake without
exposing private cooldowns in action receipts. The built-SPA journey
shows nearby physical travel, sleep and social activity at desktop/mobile sizes without exposing
future plans. Use the existing Playwright/Chromium fallback; no Browser plugin is installed.

Daily planning tests live in `tests/unit/population/test_planning.py`,
`tests/integration/test_population_planning.py` and `tests/e2e/test_population_planning_isolated.py`.
They compare coarse/split daily choices, midnight quotas, rain shelter, goals interrupted by
appointments, injury, displacement, missing food, fatigue during a commute and blocked alternatives.
Durable tests inject ledger-boundary rollback, retry once, recreate the API, run two actual workers
and restart mid-reaction, verify replay and role/world/scene privacy. The built-SPA journey observes
shelter/rest and completed daily work on desktop/mobile without private goal IDs or planner traces.
No provider or live application database is used.
Review regressions cover homeward steps longer than retry slots during missing food, injury and
day completion, including exact partial-step retry and API restart before arrival.

Motivated NPC coverage is in `tests/unit/cognition/test_goal_motivation.py`,
`tests/unit/kernel/test_npc_goals.py`, `tests/integration/test_npc_goals.py` and
`tests/e2e/test_npc_goals_isolated.py`. It covers distinct pinned CHARACTER traits, heard beliefs
preempting work, danger/contradiction, source-confidence caps, unheard/forged/malformed evidence,
authorization and unbound identity failures, split ticks and replay. Durable cases inject rollback,
restart the API and actual world workers, revoke a captured executor's grant and race card/body
associations while preserving authored revisions. The built SPA shows only actual weeding/rest at
desktop/mobile sizes. Use the existing Playwright fallback and disposable integration databases;
run full fast/types/integration gates because the shared clock and association repositories change.
Review regressions deny a non-admin DM another owner's private unassigned card, allow own or
already world-assigned cards, and verify reference/durable parity and exact retry. Actual perceived
events push danger/importance evidence outside the 80-entry presentation window; active choices
must persist through unrelated events, correction and a fresh API without expanding that window.

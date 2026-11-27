# Testing

Party API tests cover redacted receipts, intended-recipient and body authority, decline, voluntary
membership, ordinary and hostile exits, and causal reunion. The PostgreSQL test restarts the API
around consent, verifies an exact retry, and rebuilds the recorded outcome through replay.
The resident-runner cases use opposing persona traits to exercise acceptance and decline.
The durable case restarts the worker after handoff and checks the committed `NPC_POLICY` response.
Party coordination tests exercise separately authorized leadership, plan changes, travel agreement,
normal movement, cache deposits and local withdrawals, and the effect of distance on testimony.
PostgreSQL cases rebuild the party after cache use and autonomous travel.
The [Section H acceptance journey](verification/section-h/acceptance.md) covers the resident's
autonomous party role, an explicit human takeover, voluntary departure, and a funded opportunity
that survives the original giver's death.
The Chromium quest journey checks the original route and an alternate route. It verifies item
prerequisites in both console views, progress for the completed route, and the mobile reward flow.
The GitHub PostgreSQL integration job allows 70 minutes for the full suite and dependency cleanup.

Recap cases compare pre-handoff, in-window, and post-takeover actions. The PostgreSQL case
checks the returning owner's access to a machine-recorded timeout handoff across restart and
matches the narrated source to the committed revision. The built console shows the recap after
reconnect and isolates it across viewpoint changes.

The [Section G supplemental checks](verification/section-g/four-criteria.md) verify profile
versions and rebuilds, concurrent takeover, recap authorization, and the actual console requests
for handoff and return.

The [Section G completion evidence](verification/section-g/completion-proof.md) includes the
persisted player-choice record after a masked attack and the campaign pause policy as seen by
a player before handoff and after reconnect.

The [Section G review follow-up](verification/section-g/reviewer-followup.md) adds direct
checks for dialogue links, learned risk and relationship-based choices, private correction
notices, identity across reconnect, and the worker's independent authority.

Controller presence cases exercise default manual control, owner opt-in and renewal, stale epochs,
competing PostgreSQL timeout workers and same-epoch write restrictions. The browser journey leaves
the actual console for the configured deadline, returns after one autonomous action, and takes
control of the same character. Its visible event feed contains the action and no handoff metadata.

Cadence cases demonstrate short and elaborate human replies, verify the exact supporting event
IDs, and check that autonomous speech keeps the learned intent and volume. PostgreSQL replay of
the choice profile after restart retains the same cadence. Loopback provider cases check the
request and exercise both a valid generated reply and a fallback for a mismatched length.

Decision-origin verification checks manual choices, operator commands, separate stand-in
authority, and NPC policy and model labels. PostgreSQL tests inspect the committed command and
model trace after separate worker execution. The existing character experience tests check the
same sensory boundary, and migration tests cover the expanded ledger constraint.

The controller handoff unit and PostgreSQL runner suites exercise an intervening heal that makes
a queued self-heal invalid. They check that the runner rebuilds context, rejects the old attempt,
and commits one replacement. The PostgreSQL test restarts the worker between attempts and checks
the command and event ledger for duplicates.

`test_character_plans.py` covers recovery planning in both verification lanes. The unit cases
exercise injury relief, a pursuing attacker and cooldown. The PostgreSQL case restarts the worker
between a committed withdrawal and MEND, verifies the predecessor command and rejects a receipt
lookup for another body.

Decisions with a configured model are tested through a loopback Chat Completions fixture and the
durable runner. The tests cover scoped action selection, matching evaluation runtime, reported
usage, bounded retry, context rejection, deterministic fallback, and one receipt per proposal key.
A real PostgreSQL command commits while a fixture provider is waiting.

Conversation verification checks the frozen speech cue, due time, and reply grounding. The
PostgreSQL case holds the original perception delivery, restarts the worker, and verifies one
committed reply with the same language, volume, cause, and correlation. Existing generated
dialogue tests also exercise fallback through the normal speech handler.

The world-time and population tests exercise activity due times at start, during rain, after
resumption, and at completion. They verify that a finished meal charges food once, preserves
the same activity record after replacement, and survives a PostgreSQL restart and a command
retry. The existing rest and life-plan cases compare physical state across whole and split
clock advances. A player view must still reveal only the perceived activity summary.

The meal interruption cases exercise simple routines, scheduled life and daily planning.
They assert a waiting work record with its original ID, the hunger cause and exact simulated
second, the same cause on the meal, and retained interruption history when work resumes.

World due-work integration cases race two claims, recover an expired lease with a fresh runner,
deny stale tokens, inject failed event publication, and verify the retry advances the clock
once and replaces its due row. They also cover pause cancellation, actor scope and retry backoff.
The existing world-time lane runs separate processes without viewers and tests restart.
Its restart test uses a dedicated migrated database. Both subprocesses still compete on the
same due clock, and their deadline and exact persisted-tick assertions are unchanged.

The projector-ordering integration case holds one event at the branch head while a second
worker attempts to claim later work. It interrupts projection after persisting observations,
checks that character advice waits through the retry, and verifies each original observation
exists once after the second worker drains the branch.

The separate-process receipt-revocation case in `tests/integration/test_quest_evidence.py` first
proves the database grant is revoked while the original API cache still says read-all. It then
requires both a new reward response and a cached acceptance receipt to exclude private quest
deltas, preserving original event/hash and leaving no retry writes. It failed before the bounded
current-capability read and passes with that fix, alongside the four existing durable quest cases.

Quest/offer receipt regressions assert that ordinary submissions and cached retries omit private
projection deltas and source/target provenance, privileged world-manager inspection remains
available, and the pure presenter leaves canonical result bytes unchanged. The durable quest
restart/retry/replay case also checks receipt redaction without losing stored source evidence.

Quest coverage is in `tests/unit/kernel/test_quest_evidence_api.py`: all-objective completion,
unique defeats, post-acceptance offscreen work, funded rewards, settlement/retry, physical giver
availability, reference-only forgery rejection, ownership, public/fiction privacy and human/agent
trial parity. `tests/integration/test_quest_evidence.py` checks actual PostgreSQL source-command
provenance, restart/replay, late retries, concurrent reward workers and atomic physical/evidence
rollback on publication failure. `tests/e2e/test_quest_evidence_isolated.py` runs the built SPA:
accept a perceived offer, move, deliver through an authorized trade, observe journal progress,
claim once on mobile, and reject forged progress/reward syntax without a command request. It
also checks focus, console errors and horizontal overflow. These gates do not claim autonomous
quest planning or whole-campaign acceptance.

Trade authority regressions are in `tests/unit/kernel/test_trade_offers_api.py`: fixed maker terms,
carried escrow conservation, contact/visibility/incapacity, forged intent rejection, both-body
costs, passive rest interruption, expiry/partition/refund, retries and human/agent trial parity.
`tests/integration/test_trade_offers.py` uses actual PostgreSQL for restart, late retry, expiry,
recorded replay, publication rollback and concurrent separate workers. Existing final-weapon
trade regressions now require explicit buyer consent and retain equipment/read/replay assertions.
`tests/e2e/test_trade_offers_isolated.py` exercises the built SPA at desktop/mobile sizes: select
a perceived quote, prepare/focus and submit, refresh remaining stock, and reject a withdrawn offer
without losing the draft. It checks console errors and document overflow. Parser tests reject
invented taker terms. These tests verify C6 trade wiring, not autonomous quest/planning completion.

`tests/unit/kernel/test_derived_combat_api.py` covers STR/finesse/training math, stale flat-bonus
override denial, explicit legacy profiles, real seeded damage, owned equipment, manager/player
authority, forged stats/resources, late configuration retry, card isolation, in-world sensory
summary and HUMAN/AGENT trial parity. `tests/integration/test_derived_combat.py` verifies actual
PostgreSQL stat/equipment restart, retries, replay and injected publication rollback without
inventory/cost changes. Frontend parser/live-sheet regressions cover intent-only equipment and
canonical score display through one existing request. The actual built-SPA journey
`tests/e2e/test_derived_combat_isolated.py` equips a shortsword, observes a canonical score/bonus
change, then equips a spear on mobile while offscreen gardening advances on the same clock.

Initiative cases in `tests/unit/kernel/test_initiative_api.py` cover seeded order, own-only wait,
invalid/overlapping/outsider requests, human/agent trial parity, concurrent retries, partitioned
offscreen work and actual autonomous runner suspension/resume without budget loss. Durable tests
in `tests/integration/test_initiative.py` verify restart, late seed-override retry, replay, concurrent
transactions and injected event-publication rollback. Canonical score ownership also runs through
the reference and durable character-resource regressions. The actual Chromium journey in
`tests/e2e/test_initiative_isolated.py` preserves a rejected off-turn draft, advances the clock,
then commits the same intended guard and checks desktop/mobile rendering.

Rest regressions in `tests/unit/kernel/test_rest_recovery_api.py` cover fixed thresholds/caps,
long-rest cooldown, physical/damage interruption, denied parameter overrides, incapacity,
human/agent trial parity, offscreen routine/sleep recovery and whole-versus-split clock advances.
`tests/integration/test_rest_recovery.py` verifies actual PostgreSQL restart, late retry,
recorded replay and injected atomic rollback of body/activity/clock/ledger. The built-SPA
`tests/e2e/test_rest_recovery_isolated.py` submits `/rest long`, observes live 2/12→5/12→12/12
health and mana recovery, then interrupts a short rest from the mobile console with `/guard`.

Death/recovery regressions cover exact six-second saves, natural 1/20, stabilization, death,
clocked recovery, permanent-condition preservation, trusted seed provenance, late retries,
whole/split advances, 0-HP healing, dead-target rejection and contact/forged first aid. New
dead/unconscious sight/sound grants are rejected. Run `uv run python -m pytest
tests/unit/kernel/test_death_recovery_api.py`. The integration lane for
`tests/integration/test_death_recovery.py` verifies actual PostgreSQL restart, seed/timer
preservation, recorded replay and rollback after an intermediate save. The built-SPA journey
`tests/e2e/test_death_recovery_isolated.py` sends first aid through the human console and observes
stable recovery without editing the authored card.

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

Scoped narration tests verify the reference and PostgreSQL routes with committed speech and
movement. The durable lane covers retention across restart, current authorization, composite
source constraints, append-only grants, and upgrade from migration 014. The wheel gate checks
that migration 015 ships with the application.

Character recovery tests cover an isolated movement cycle, repeated no-damage attempts and a
bounded speech chain with missing or foreign observations. The PostgreSQL test commits a
movement cycle, restarts the runner, verifies the alternative offered to its provider, and checks
the final controller step and pause after one committed recovery.

The [Section F unattended cast verification](verification/section-f/acceptance.md) runs the
production projector, character runner, and world runner against isolated PostgreSQL. It requires
no external model account. A local OpenAI-compatible fixture returns grounded dialogue or HTTP
503, and both scenarios must reach the same clock boundary with stable consequences on restart.
The proposal concurrency regression forces a paused clock advance to hold the branch while
proposal persistence acquires the run lock. Both receipts must commit and remain readable.

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

The tactical choice lanes verify human self-heal versus assistance priority, exclusion of
strangers and former helpers who attack, comparable opportunities, restart stability, and
distinct human preference versus machine execution attribution for the resulting MEND.
An unoffered action retains its fallback when other choices have human evidence. The Section G
campaign integration test plays solo, mixed and all-autonomous phases on one run with two
character seats, the real projector, and competing durable workers. It also checks a
history-free companion's backstory choice, unchanged sensory context at handoff, and trial
history isolation after restart.
The durable presence test offsets the API and runner clocks from PostgreSQL by two minutes,
then exercises renewal, restart and timeout. It uses the real database trigger.

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

`tests/unit/kernel/test_population_resolution.py` and the durable population lane verify the
offscreen-to-detailed transition through real controls and physical party movement. They check
unattended work, an unchanged controller budget, rejection of a prepared action after departure,
and one authorized action when the party returns. The durable case uses a fresh application
instance and the real PostgreSQL controller store. The test pauses its clock and controller
after verification so later cases sharing the test database use their own scheduled work.
GitHub allows up to 50 minutes for the complete PostgreSQL integration lane.

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

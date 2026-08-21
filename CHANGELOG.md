# Changelog

## Spatial epistemics

- Added explicit `entity.act` authority and controlled-body requirements for embodied commands.
- Added a shared deterministic event finalizer and entity-scoped frozen `PerceptionGrant` records.
- Added migration 003 with append-only perception grants, belief evidence, provenance links, RLS,
  and retry-safe durable persistence.
- Added grid zones, portals, occluders, sight, sound, event-time context hashes, and embodied speech.
- Replaced the Player Game Console's canonical map/event reads with a viewpoint-scoped scene and
  observation feed; distant entities degrade to anonymous presences rather than leaking details.
- Added testimony provenance and selective memory consolidation so routine movement does not fill
  permanent memory.

This file records the current TableTop DM product line.

## Unreleased

### Security

- Bound every command, event read, cognition decision, observation, and mind inspection to the
  actor of the signed-in account. Previously the actor came from the request, so any authenticated
  account could act and read as any actor, including the administrator's, and the ledger recorded
  the impersonated actor rather than the caller. Only the operator/automation token may still name
  another actor.
- Required the Administrator role to list or create simulation actors. An actor carries world
  capabilities, so an unguarded `POST /api/v2/actors` was a capability mint.
- Added world-scoped authorization to every control-plane read, including
  `GET /api/v2/branches/{branch_id}/replay`. Worlds, runs, branches, snapshots, and events now list
  only the caller's worlds; roles are never unioned across worlds.
- Provisioned simulation authority from product roles through
  `identity.repository.kernel_authority`, so a `DM` or `PLAYER` grant reaches the kernel on the
  account's next sign-in in both reference and durable modes rather than only after a restart. A
  Player receives `world.read`, `action.propose`, and `action.commit`, and no entity control.
- Moved `/api/v2/trials` behind the Administrator boundary, replacing a routeless
  `/api/v2/experiments` prefix that guarded nothing.
- Excluded disabled administrators from the final-administrator guard, which could otherwise be
  satisfied by an account that cannot sign in and leave an installation with no usable
  administrator. The last administrator who can still sign in can no longer be disabled either.
- Stopped failed logins during an active lockout from extending it, and reset the failure count
  once a lockout lapses. Previously an attacker could hold any account locked indefinitely by
  guessing at the username, first by extending the window and then by re-locking it with a single
  attempt per window.

### Testing

- Added `tests/integration/test_durable_authorization.py`, asserting that session-bound actor
  binding, world scoping, event visibility, and actor minting reach the same outcomes against
  PostgreSQL and row-level security as they do in reference mode.
- Marked `tests/unit/identity/` and `tests/unit/domains/` with `pytest.mark.unit`. Neither carried
  a marker, so `pytest -m "unit or contracts"` — the fast gate and the CI lane — silently skipped
  all eight tests in them.

## 2.0.0 - 2026-08-20

### Platform and identity

- Added secure account login with HTTP-only sessions, forced first-login password replacement,
  password policy enforcement, failed-login lockout, and append-only identity audit records.
- Added global Administrator access and world-scoped Dungeon Master and Player roles, including
  combined DM + Player access.
- Added Administrator account management for creation, editing, enable/disable, deletion,
  password reset, global roles, and per-world roles.
- Added profile settings for display/legal name, email, date of birth, pronouns, timezone,
  locale, biography, avatar URI, password changes, and sign-out.

### Tabletop workspaces

- Added a Player Dashboard for saved characters, character statistics, alive/dead status,
  deterministic generation, manual building, and JSON template import.
- Added a Dungeon Master workspace for hosted games, game status, rosters, player-character
  assignments, session scheduling, safety notes, house rules, and private DM notes.
- Added a typed Game Console for dialogue, movement, combat, and spell proposals against
  canonical public state.
- Added the Control Plane, Persona Studio, Population Studio, Scenario Lab, Run Inspector, and
  Calibration workspaces with role-aware navigation.
- Added engine-neutral Tactical, Third Person, and First Person control-mode contracts over one
  battle state, five persistent squad-AI orders, unified aggregate/direct weapon statistics, and
  perception-scoped renderer/input ports for a future external engine.

### Simulation kernel

- Added a domain-neutral world/run/interaction kernel with world-scoped actors, capabilities,
  controlled entities, typed commands, deterministic handlers, atomic projections, append-only
  ledgers, visibility, snapshots, isolated branches, replay, and reviewed promotion.
- Added tabletop domain commands for entity creation, dialogue, movement, combat, magic,
  economy, factions, divine effects, quests, content rating, and onboarding.
- Added a modular 80-dimension persona fabric with dependencies, constraints, seeded generation,
  validation, provenance, immutable versions, compilation, and bounded prompts.
- Added subjective cognition with observations, beliefs, memories, relationships, reflexes,
  utility scoring, bounded GOAP planning, runtime assignment, and typed deliberation.
- Added statistical, materialized, and active population layers using Parquet, DuckDB, and
  PostgreSQL lifecycle projections.
- Added immutable scenarios, trial execution, resumable jobs, normalized verifier facts,
  metrics, cohort reports, comparison, calibration review/promotion, and opt-in telemetry.

### Durability and security

- Added PostgreSQL schemas for simulation, identity, tabletop portals, artifacts, personas,
  cognition, populations, and experiments.
- Added Redis/RQ experiment queues, Qdrant readiness and semantic-lore integration, and a shared
  content-addressed artifact volume.
- Added forced row-level security, least-privilege runtime credentials, append-only evidence
  triggers, composite world/branch/run keys, actor transaction context, and secret entity-state
  controls.
- Added durable replay bases, idempotent command receipts, transactional outbox records,
  restart hydration, population transition history, scenario/job/trial/report restoration, and
  consent-aware telemetry deletion and retention.
- Added generated local secrets, loopback-only published ports, browser session authentication,
  and a separate automation operator token.

### Delivery and verification

- Added a multi-stage, read-only, unprivileged production image and Docker Compose topology for
  PostgreSQL, Redis, Qdrant, migration, API, and worker services.
- Added deterministic unit and contract tests, real PostgreSQL/Redis integration tests, React
  component tests, production bundle checks, wheel-runtime verification, and Playwright journeys.
- Added CI quality, integration, frontend, image, browser, and tagged GHCR publication lanes.
- Added complete architecture, API, operations, testing, network, and agent-maintenance guides.

### Constitutional guarantees

- Models never own world truth.
- Persona identity is independent of the runtime executing it.
- Canonical truth, observation, belief, memory, and narration are distinct records.
- Every stochastic or model-assisted decision records reproducibility provenance.
- All canonical mutations pass through typed validation and authorization.
- Experiment branches cannot mutate canonical state.
- Verifiers emit normalized facts with evidence, not persuasive prose.
- Synthetic outputs are hypotheses, not human ground truth.

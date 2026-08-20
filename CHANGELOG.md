# Changelog

This file records the current TableTop DM product line.

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

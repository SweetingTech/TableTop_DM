# Changelog

All notable changes to TableTop DM are documented here. V2 is a clean-break release; the v1
history remains available from the tag `v1-behavioral-reference-2026-08-17`.

## 2.0.0 - 2026-08-17

### Breaking changes

- Replaced the RPG-specific core with a domain-neutral simulation kernel using world, run,
  interaction, actor, branch, command, event, and projection contracts.
- Replaced principal enums with human/agent/system actors plus roles, capabilities, and explicit
  embodied-entity control.
- Replaced the v1 schema chain with one fresh-install baseline,
  `001_simulation_kernel.sql`. V1 database and save-file migration is intentionally unsupported.
- Removed the v1 Flask monolith, server-rendered templates, legacy static client, release bundle,
  seed/init SQL, and RPG-specific core contracts from the active tree.
- Moved tabletop rules behind the `domains.tabletop` command registry.

### Added

- Atomic typed command handling with deny-by-default authorization, idempotent receipts,
  correlation/causation IDs, state hashes, and versioned event provenance.
- Canonical and trial branches, immutable compressed snapshots, replay verification, and an
  explicit reviewed consequence-promotion command.
- Tabletop command packs for dialogue, movement, combat, magic, economy, factions, divine
  effects, quests, and simulated-player onboarding.
- A modular 80-dimension persona schema across core, world, tabletop, and accessibility packs,
  with dependency-aware seeded generation, validation, provenance, immutable versions,
  compilation, and prompt budgets.
- Subjective cognition with perception filters, observations, beliefs, memories, relationship
  vectors, reflexes, utility scoring, bounded GOAP planning, and typed deliberation proposals.
- Statistical, materialized, and active population levels backed by Parquet and DuckDB cohort
  operations.
- Scenario definitions, isolated trial execution, resumable job state, normalized verifier
  facts, metrics, cohort reports, comparisons, calibration review gates, and opt-in telemetry.
- A React application with URL-addressable Game Console, Control Plane, Persona Studio,
  Population Studio, Scenario Lab, Run Inspector, Calibration, and Settings workspaces.
- Full Control Plane creation workflows for world-scoped actors, embodied entities, live or
  experimental runs, canonical snapshots, and snapshot-based trial branches.
- Typed Game Console slash commands and map tokens derived from canonical public `x`/`y` state.
- Separate calibration review and promotion actions; promotion registers an immutable deployable
  policy version without silently changing runtime assignments.
- PostgreSQL, Redis, Qdrant, API, worker, migration, and artifact services in a managed Docker
  Compose stack.

### Storage and security

- Added separate PostgreSQL schemas for simulation, artifacts, personas, cognition, populations,
  and experiments.
- Added durable boot hydration for worlds, branches, actors, entities, runs, snapshots, events,
  persona versions/profiles, cognition evidence, population catalogs/activation state, and
  scenario definitions.
- Added durable command replay history and snapshot-basis reconstruction, world-scoped population
  lifecycle continuation, and artifact/PostgreSQL rehydration for experiment jobs, trials,
  normalized reports, and registered scenario versions.
- Added immutable, source-event-linked relationship change history and world-scoped
  `entity.read.secret` enforcement alongside public-only entity projections.
- Added immutable calibration artifact reload plus PostgreSQL-backed telemetry settings and
  captures with consent-gated export, import, selective deletion, and retention purging.
- Added composite world/branch/run foreign keys and branch-scoped entity identity so trial
  branches can retain logical entity IDs without crossing worlds.
- Added append-only database enforcement for command/event ledgers and immutable evidence
  records.
- Added forced row-level security for canonical projections, entities, ledgers, subjective
  cognition, and telemetry captures; missing or malformed actor context fails closed.
- Separated owner-only migration credentials from the least-privilege runtime login.
- Added localhost-or-operator-token HTTP protection. Managed deployments generate secrets rather
  than copying CI credentials, bind published ports to loopback, and keep browser tokens
  session-scoped.
- Kept human telemetry local, disabled by default, redact-sensitive, consent-gated, immutable
  after capture, and explicitly deletable for consent withdrawal or retention expiry.

### Verification and delivery

- Added deterministic unit and contract suites for the kernel, domain rules, personas,
  cognition, populations, experiments, migrations, and API.
- Added an explicit Phase-0 behavioral-reference manifest pinning the retrievable v1 tests,
  fixtures, release evidence, and bundle to commit
  `93e02846e4d73097afc65f2dfd684a8a7e49966b`.
- Added clean-database, migration checksum, RLS, append-only ledger, durable command/replay,
  relationship causality, population lifecycle, experiment restart, and worker integration tests.
- Added React component journeys and Playwright user journeys across all eight workspaces.
- Added lint, formatting, static type, frontend build, integration, production-image, and browser
  CI lanes.
- Added a multi-stage, read-only, unprivileged production image and tagged-image publication to
  GHCR.

### Constitutional guarantees

- Models never own world truth.
- Persona identity is independent of the runtime executing it.
- Canonical truth, observation, belief, memory, and narration are distinct records.
- Stochastic and model-assisted decisions carry seeds and version provenance.
- Experiment branches cannot mutate canonical state.
- Verifiers produce normalized facts with evidence, not persuasive prose.
- Synthetic output is labeled as hypothesis, never human ground truth.

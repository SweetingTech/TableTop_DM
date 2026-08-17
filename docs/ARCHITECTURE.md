# Architecture and invariants

## System shape

The kernel owns identity, authority, state transactions, events, visibility, snapshots,
branching, and replay. Domain packages register commands; they do not bypass those facilities.

```text
React / CLI / agent runtime
          |
          v
   typed proposal API
          |
          v
 capability + control check -----> reject without mutation
          |
          v
 deterministic domain handler
          |
          v
 atomic branch projection + append-only command/event + outbox
          |
          +------> subjective observation/belief/memory
          +------> verifier facts and metrics
          +------> optional narration
```

`world_id`, `run_id`, and `interaction_id` are the neutral contract. A tabletop campaign,
session, and encounter are domain aliases rather than kernel primitives.

## Actors and authority

An actor identity is `HUMAN`, `AGENT`, or `SYSTEM`. Its roles, capabilities, and controlled
entities are stored as explicit `(world_id, actor_id)` authority records; grants in one world
never leak into another. The current domain uses capabilities such as `world.read`,
`entity.control`, `entity.read.secret`, `action.propose`, `action.commit`, `run.branch`, and
`canonical.promote`. Entity collection projections are public-only. A controller or actor with
world-scoped `entity.read.secret` may cross the separate secret-state visibility boundary; a
grant in another world is irrelevant.

Command definitions declare:

- a stable command type and version;
- a typed request and optional typed result;
- required capabilities;
- canonical and/or trial branch eligibility;
- a pure handler returning `CommandResult` and `StateDelta` values.

Authorization is deny-by-default. Commands requiring `entity.control` also verify that the actor
controls the proposed embodied entity. PostgreSQL repeats world-scoped actor checks through
forced RLS on durable state.

## State, commands, and events

`BranchState` contains named projections, a monotonically increasing version, and a stable
SHA-256 state hash. Supported delta operations are `SET`, `MERGE`, `DELETE`, and `INCREMENT`.
The in-memory store executes against a copy and publishes it only after the handler and deltas
succeed. The PostgreSQL repository locks the projection row and writes the projection, command,
event, and outbox record in one transaction.

`EventEnvelopeV2` records world, branch, run, interaction, actor, embodied entity, visibility,
observation scope, parent/correlation/causation IDs, domain tags, idempotency, seed, decision
trace, persona/policy/prompt/model versions, and creation time. This is enough to explain and
replay a decision without treating a model response as authoritative state.

## Canonical state and trial branches

Each world has one canonical branch. A snapshot is a deterministic gzip artifact containing the
projection state, sequence, contract version, and content hashes. A trial branch loads that
snapshot and preserves logical entity IDs under a new branch-scoped primary key.

Trials may execute commands and produce their own ledgers, verifier facts, and metrics. They do
not write the canonical projection. Promotion is a separate canonical command requiring:

- `canonical.promote` and `action.commit` capabilities;
- a source trial branch;
- explicit deltas and a human review note;
- the expected current canonical state hash.

The state-hash precondition prevents promotion after the reviewed canonical basis has changed.

## Persona fabric

The schema registry loads 80 dimensions from four YAML packs:

- `core`: cognition, personality, values, communication, social style, risk, and habits;
- `world`: species, culture, religion, class, education, occupation, and factions;
- `tabletop`: player style, rules familiarity, combat/exploration/roleplay preferences, and
  metagaming tendencies;
- `accessibility`: reading, visual, motor, cognitive, and interface needs.

Generation is dependency ordered and seed based. Fixed assignments and weighted distributions
are validated against allowed values and declarative conditional constraints. Each field keeps
its source, pack, schema version, generator version, seed, distribution, and applicable rules.

The compiler turns a blueprint into policy weights, an identity summary, initial goals, beliefs,
relationships, routines, capability modifiers, retrieval filters, and deep traits. Prompt
assembly includes only requested relevant traits and enforces token and character budgets.

## Subjective cognition

Canonical truth and cognition are deliberately separate:

```text
event -> perception filter -> observation -> belief revision -> memory
                                      \----> relationship change
```

Perception accounts for event visibility, actor identity, acuity, payload allow/deny fields, and
confidence bias. Beliefs retain subject/predicate/value, confidence, evidence, and contradiction
history. Memories retain summaries, emotional weight, importance, visibility, and recall
strength. Relationships are vectors rather than one tension score. Every relationship update is
an immutable causal record containing its source event, actor, world/branch, before/after
vectors, requested/applied deltas, and policy version. The source event must be visible and in
the same world branch; causal retries are idempotent and cannot rewrite history.

The layered decision engine evaluates, in order:

1. deterministic reflex rules;
2. seeded utility scoring;
3. bounded GOAP planning;
4. typed deliberation for ambiguous or novel cases when enabled.

Every tier returns a `DecisionTrace` and a typed proposal. Even an LLM-selected action must be in
the supplied action set and still crosses the command bus. If no provider is configured, the
deliberation gateway falls back to the deterministic utility result.

## Population engine

Population work has three levels:

| Level | Representation | Intended use |
| --- | --- | --- |
| Statistical | Parquet profiles queried by DuckDB | large pools, distributions, filters, cohorts |
| Materialized | persistent person profile and compressed state | households, work, beliefs, finances, scheduled background updates |
| Active | materialized person plus attention/scene state | detailed perception, decisions, planning, and optional deliberation |

Generation streams batches rather than retaining the full pool in memory. Cohorts support fixed
filters, deterministic stratified cells, weighted sampling, explicit feasibility diagnostics,
and distribution-tolerance reports. Activation and deactivation are versioned transitions that
preserve persistent state. Pool targets and every lifecycle request carry the same immutable
`world_id`/`branch_id`; a pool cannot be activated into whichever world happens to be selected
later. PostgreSQL restores materialized, active, and compressed members plus their monotonic
transition history.

## Scenario and evaluation lab

A scenario definition is immutable by `(scenario_id, version)` and can declare a base snapshot,
cohort, intervention, allowed actions, horizon, stop conditions, model assignment, seeds,
verifier versions, and metric contract. Each selected persona/seed combination becomes an
isolated trial with its own branch and run identity.

Trial runners emit normalized output. Verifiers emit facts with evidence event IDs and explicit
versions; metric evaluators reduce those facts to numeric results. Aggregation reports cohort
statistics and comparisons. Jobs expose queue/running/checkpoint/terminal state and bounded
retry behavior. The reference runner composes any registered definition through the same typed
trial-branch executor; onboarding is one registered definition rather than a special persistence
model.

Calibration is a review boundary. It compares metrics against separately versioned human
evidence and proposes policy adjustments. Review and promotion are explicit immutable artifacts;
the engine never rewrites the supplied evidence. Promotion places the approved immutable version
in the registry as a deployable candidate; it does not rewrite cognition mappings or
automatically reassign a live runtime.

## Durability and restart boundary

The durable composition root reconstructs control-plane worlds, branches/projections,
world-scoped actor grants, entities, runs, snapshot manifests, command replay records, replay
bases/offsets, and event envelopes from PostgreSQL. Each clean-v2 branch persists a pre-command
snapshot basis before its first durable command, and later snapshots may preserve the same state
hash at distinct command boundaries. Domain repositories
restore persona schema/version/profile records, cognition evidence, population catalogs and
materialized/active/compressed membership plus immutable transition history, scenario
definitions, and telemetry settings/captures. The experiment history store and PostgreSQL
repository restore registered scenario versions, job lifecycle/checkpoints, normalized
`TrialOutput` records (including event envelopes), and cohort reports. Calibration proposal,
review, and promotion history reloads from immutable artifacts.

Terminal jobs and their report/trial inspection views survive API restart. A job whose last
durable status was `RUNNING` is restored as failed because the new process cannot prove whether
an external side effect completed; the explicit retry endpoint reattaches the registered runner
and starts a bounded new attempt. Deterministic branch replay, population lifecycle continuation,
experiment inspection, and their audit histories do not depend on the process that originally
executed them. Local-reference mode retains filesystem-backed experiment and calibration history
but intentionally does not make canonical worlds, cognition, or population lifecycle projections
durable without PostgreSQL.

## Package map

```text
kernel/              neutral state and authority
domains/tabletop/    first domain command pack
persona/             schemas, generation, validation, compilation, versions
cognition/           subjective state and layered decisions
population/          pools, cohorts, and activation lifecycle
experiments/         scenarios, trials, verification, reports, calibration
kernel/api/          Flask HTTP composition root
frontend/            React operator application
infra/               baseline schema, migration runner, and Compose stack
scripts/             lifecycle and test entry points
tests/               unit, contract, integration, and browser journeys
```

## Non-negotiable invariants

1. Models never own world truth.
2. Persona identity is independent of the runtime executing it.
3. Canonical truth, observation, belief, memory, and narration are different objects.
4. Persona profiles and scenario definitions are versioned and reproducible.
5. Every stochastic decision records its seed.
6. Model-assisted decisions record prompt contract, model, policy, persona, and trace versions.
7. All world mutation passes through typed command validation and authorization.
8. Trial branches cannot mutate canonical state.
9. Verifiers emit normalized facts with evidence, not persuasive prose.
10. Synthetic results are hypotheses, not human ground truth.

The frozen v1 oracle used to establish the clean-break baseline is independently pinned in the
[Phase 0 behavioral-reference manifest](V1_BEHAVIORAL_REFERENCE.md); it is not part of this
runtime architecture.

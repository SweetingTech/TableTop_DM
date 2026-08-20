# API and user workflows

The Flask service exposes JSON under `/api/v2` and serves the React application under `/v2`.
Pydantic request validation returns HTTP 400, missing resources return 404, and authorization or
branch-isolation errors return 403. Health endpoints are intentionally outside the operator
boundary.

## Accounts and sessions

The durable application creates a bootstrap `admin` account with the password `admin123` and
requires that password to be changed before any protected workspace is available. Successful
sign-in issues a 12-hour HTTP-only, SameSite session cookie. Password changes, administrator
resets, role changes, account disabling, and deletion revoke existing sessions.

Administrators assign global `ADMIN` access and world-scoped `DM` and `PLAYER` roles. The same
account may hold both tabletop roles. Player routes require Player authority, DM hosting routes
require DM authority for the target world, and persona/population/scenario/calibration studios
require Administrator authority.

The legacy `X-TTDM-Operator-Token` remains available for local automation. It is not shown in the
web interface and is not needed by human users. Cross-site browser writes are rejected, and the
provided stack publishes every port on loopback only.

Some canonical actions, such as consequence promotion, also accept `X-TTDM-Actor-ID` to select
the capability-bearing actor. Database transactions set the corresponding `app.actor_id` for
RLS enforcement.

## Discovery and health

| Method and path | Purpose |
| --- | --- |
| `GET /healthz` or `/api/v2/health/live` | Process liveness |
| `GET /readyz` or `/api/v2/health/ready` | PostgreSQL migration, Redis, Qdrant, and application readiness |
| `GET /api/v2/meta` | Contract/schema versions, modes, telemetry setting, and invariants |
| `GET /api/v2/bootstrap` | Demo world IDs and registered command contracts |
| `GET /api/v2/commands/contracts` | Typed command schemas, versions, required capabilities, and branch kinds |
| `GET /api/v2/contracts/persona-schema` | Persona schema contract |

Readiness returns HTTP 503 if a configured dependency is unhealthy or PostgreSQL is not at
`002_identity_and_tabletop_workspaces.sql`. With no external URLs configured, it explicitly reports
`local_reference` mode.

## Web and static routes

`GET /v2` and every `/v2/*` workspace path return the React history entry point. Production
Vite bundles are served from `GET /static/v2/<path>`; application-owned images are served from
`GET /assets/<path>`. The explicit build-asset route runs before the SPA fallback, so JavaScript
and CSS receive their real content and MIME types rather than `index.html`. Unknown `/api/*`
paths return JSON 404 responses.

## World and command flow

1. Create or select a world in **Control Plane**.
2. Create actors/entities as needed and start a live, population, or evaluation run.
3. Inspect `/api/v2/commands/contracts` for the exact input schema.
4. Submit a proposal to `/api/v2/commands` with all identity fields and a stable idempotency key.
5. Read the returned deterministic result, canonical state hash, and event.
6. Inspect actor-visible events, branch state, or replay from **Game Console** and **Run
   Inspector**.

The Game Console translates `/move north|south|east|west`, `/attack <entity>`, and
`/cast <target> <damage|heal|condition> <power> <mana> <spell>` into typed command proposals.
Unprefixed text remains typed dialogue. Map tokens use each entity's public canonical `x`/`y`
coordinates; the client does not invent per-entity positions.

The demo bootstrap lets a local smoke test omit IDs:

```powershell
$body = @{
  command_type = 'tabletop.console.submit'
  parameters = @{ text = 'I ask the gatekeeper about the missing caravan.' }
  idempotency_key = 'docs-dialogue-1'
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v2/commands `
  -ContentType application/json `
  -Body $body
```

Production callers should supply this complete envelope:

```json
{
  "command_type": "tabletop.spatial.move",
  "world_id": "00000000-0000-0000-0000-000000000000",
  "branch_id": "00000000-0000-0000-0000-000000000000",
  "run_id": "00000000-0000-0000-0000-000000000000",
  "actor_id": "00000000-0000-0000-0000-000000000000",
  "embodied_entity_id": "00000000-0000-0000-0000-000000000000",
  "parameters": {"dx": 1, "dy": 0},
  "idempotency_key": "client-action-000042",
  "seed": 101,
  "persona_version": "<version>",
  "policy_version": "layered-cognition-1.0.0"
}
```

Correlation, causation, interaction, decision-trace, prompt-contract, and model IDs can be added
when relevant. Repeating the same run/actor/idempotency tuple is a retry, not a new action.

World endpoints include:

- `/worlds`, `/worlds/{world_id}`, `/worlds/{world_id}/actors`, and
  `/worlds/{world_id}/entities`;
- `/actors`, `/runs`, `/worlds/{world_id}/runs`, `/branches`, and `/events`;
- `/worlds/{world_id}/snapshots`, `/snapshots/{snapshot_id}/branches`,
  `/branches/{branch_id}/replay`, and `/branches/{branch_id}/promotions`.

Actor creation accepts a target `world_id`; roles and capabilities are never unioned across
worlds. Entity control cannot be claimed in an actor-creation request. It is assigned atomically
by the typed entity-creation command through `controller_actor_id`, so local and durable authority
cannot diverge. Durable boot hydrates worlds, branches and projections, scoped actor grants and
controlled entities, runs, snapshots, command replay history/bases, and visible event envelopes.
`/branches/{branch_id}/replay` therefore verifies committed history after a process restart as
well as in the process that executed it. The Control Plane exposes compact forms for all of these
creation paths: actor (`POST /actors` with `world_id`), entity
(`POST /worlds/{world_id}/entities`), run (`POST /runs`), canonical snapshot, and trial branch.

Entity lists contain public projection state only. Secret state is a separate visibility
contract: only the controlling actor or an actor with `entity.read.secret` in that same world may
receive it through an authorized projection. `world.read` or a secret grant from another world
does not broaden that access.

## Persona and cognition flow

1. In **Persona Studio**, choose a seed and optional fixed dimensions.
2. Generate a blueprint. The response includes field provenance and validation status.
3. Create a manual successor version when an identity must change; pass its parent version ID.
4. Compile the selected identity into policy weights, goals, beliefs, relationships, routines,
   modifiers, and retrieval filters.
5. Assemble a bounded prompt for a concrete situation and only the requested deep traits.
6. Send allowed actions to `/cognition/decide`. The response is a decision trace and an
   uncommitted typed proposal.
7. Submit that proposal to `/commands` if the runtime is authorized to act.

Routes:

- `GET /personas/schema`, `GET /personas`, `POST /personas`, and
  `POST /personas/generate`;
- `GET /personas/{persona_id}`, `GET /personas/{persona_id}/versions`,
  `POST /personas/{persona_id}/compile`, and `POST /personas/{persona_id}/prompt`;
- `POST /cognition/decide`, `POST /events/{event_id}/observe`,
  `POST /entities/{entity_id}/relationships`, and `GET /entities/{entity_id}/mind`.

The cognition decision endpoint never commits. This deliberate two-step boundary lets an
operator inspect the trace before world mutation. In durable mode, persona schema/version and
compiled-profile records plus observations, beliefs, memories, relationships, mind projections,
and decision traces survive restart and remain actor-scoped by RLS.

Relationship writes are causal, not free-floating vector edits. Each request references a
visible `source_event_id` in the same world branch. The immutable history records actor, source
and target entities, before/after vectors, requested and applied deltas, policy version, and the
source event. A controlled actor uses registered deterministic event mappings; arbitrary deltas
or modifiers require `mind.write.all`.

## Population flow

1. In **Population Studio**, generate a named, seeded pool for an explicit `world_id` and
   `branch_id` (the demo canonical branch is used only when both are omitted). The API writes a
   Parquet artifact and persists that immutable target.
2. Filter and sample using declared strata and `per_cell`, or submit a full cohort definition to
   the feasibility endpoint.
3. Materialize selected profiles when they become persistent people.
4. Activate nearby or important people for detailed cognition.
5. Deactivate them with compressed state when they leave the relevance window.
6. Inspect the immutable transition history.

Routes and aliases:

- `GET /populations` and `GET /populations/definitions` list the same pool catalog (the UI
  filters the returned typed `world_id` to the active world);
- `POST /populations` and `POST /populations/generate` create a pool;
- `POST /populations/{population_id}/sample` and
  `/populations/{population_id}/cohorts/feasibility`;
- `POST /populations/{population_id}/materialize` and `/activate`;
- member-specific `GET`, `/activate`, and `/deactivate` routes;
- `GET /populations/{population_id}/transitions`.

The HTTP generator caps one request at 100,000 profiles; the core `PopulationDefinition` and CLI
support larger streamed pools up to five million. PostgreSQL catalogs the Parquet artifact and
restores each member's persistent, active, and compressed state, lifecycle version, monotonic
world step, and append-only transition history across API restarts. Materialize, activate, and
deactivate requests must match the pool's stored world/branch target; selecting another world in
the UI cannot transplant the pool.

## Scenario and evaluation flow

1. Capture a canonical snapshot.
2. Register an immutable scenario version with cohort, seeds, horizon, stop conditions, verifier
   versions, and metric contract through `POST /scenarios`.
3. Run any registered definition from **Scenario Lab**. The UI is a runner/inspector, not a
   scenario-authoring surface; `player-onboarding` is one registered definition.
4. Inspect job status, sample trial outputs, verifier facts, metrics, and cohort aggregation in
   **Run Inspector**.
5. Compare trials or reports. A trial never mutates the canonical branch.
6. If a simulated consequence should become real, create a reviewed consequence package and
   promote it through the canonical command boundary.

Routes:

- `GET/POST /scenarios`, `POST /scenarios/{scenario_id}/run`, and
  `POST /scenarios/player-onboarding/run`;
- `POST /experiments/onboarding/run` is the compatibility alias that returns the normalized
  cohort report directly;
- `GET /jobs`, `GET /jobs/{job_id}`, and job `/cancel` and `/retry`;
- `GET /trials/{trial_id}`, `POST /trials/compare`, `GET /reports`, and
  `GET /reports/{report_id}`.

A minimal generic definition and run look like this:

```json
{
  "scenario_id": "market-tax",
  "version": "1.0.0",
  "name": "Market tax counterfactual",
  "cohort_size": 20,
  "seeds": [101, 202, 303],
  "intervention": {
    "type": "SET_MARKET_TAX",
    "deltas": [
      {
        "projection": "tabletop.economy",
        "operation": "SET",
        "values": {"tax_percent": 15}
      }
    ]
  },
  "verifier_versions": ["scenario.reference@1.0.0"]
}
```

Register that body with `POST /scenarios`, then run it with
`POST /scenarios/market-tax/run` and an optional override such as
`{"cohort_size": 10, "seeds": [404], "include_trials": 10}`. Generic runs compose the
definition through `ApplicationBranchExecutor` and the typed `experiments.scenario.apply`
command on isolated evaluation branches. The response contains `job`, `report_id`, and `report`.

Scenario versions, job lifecycle/checkpoints, normalized trial outputs (including their event
envelopes), and cohort reports are persisted to the experiment artifact history and, when
`DATABASE_URL` is configured, PostgreSQL. `/scenarios`, `/jobs`, `/reports`, and
`/trials/{trial_id}` rehydrate after restart. A job interrupted in `RUNNING` state restores as
failed and requires explicit `/retry`; terminal jobs remain inspectable. The standalone Redis/RQ
worker remains available for serializable queued adapters.

## Calibration and telemetry flow

**Calibration** accepts synthetic and human metric dictionaries plus separate policy and
evidence versions. It calculates error and proposed adjustments, then requires an identified
operator review. Approval does not rewrite evidence or silently mutate a live policy.

- `POST /calibration/compare`
- `GET /calibration/history`
- `GET /calibration/{report_id}`
- `POST /calibration/{report_id}/review`
- `POST /calibration/{report_id}/promote`
- `POST /calibration/{report_id}/approve` (compatibility alias for an approval review only)

Calibration proposals, reviews, and policy-promotion records are separate immutable artifacts.
They are reloaded from `artifacts/calibration` at boot. Review must approve a report before the
separate promotion call can register its proposed immutable version as a deployable candidate.
Neither review nor registry promotion rewrites the original evidence, changes cognition policy
mappings, or automatically selects the new version for a live runtime. Canonical trial-consequence
promotion remains a different operation under `/branches/{branch_id}/promotions`.

Human telemetry is disabled by default. `GET /telemetry` reads settings; `PUT /telemetry` can
change `enabled` and/or `retention_days`. Capture is rejected until explicit opt-in.

- `POST /telemetry/events` records one recursively redacted capture.
- `GET /telemetry/events` and `GET /telemetry/export` are JSON export aliases.
- `POST /telemetry/import` imports up to 10,000 capture dictionaries through the same consent and
  redaction boundary.
- `DELETE /telemetry/events` supports optional `world_id`, `actor_id`, and ISO-8601 `before`
  query filters; no filters deletes every capture visible to the operator.
- `POST /telemetry/purge-expired` deletes captures older than the configured retention period.

Settings and captures use PostgreSQL in durable mode and survive restart. Captures cannot be
updated after insertion, but explicit deletion remains available for consent withdrawal and
retention expiry. Synthetic trial facts do not require human-telemetry consent because they are
labeled synthetic evaluation output, not human observations.

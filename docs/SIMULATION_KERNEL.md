# Simulation-kernel contract

TableTop DM is one domain-neutral simulation system with three execution modes:

```text
                         Simulation kernel
                                |
              +-----------------+-----------------+
              |                 |                 |
          Live world        Population        Evaluation
          persistence       distributions     snapshot branches
          active minds      cohorts           simulated players
          tabletop play     background state  normalized facts
```

Tabletop is the first domain pack, not the definition of the kernel. Persona, cognition,
population, and experiment packages do not own canonical tabletop state. Every domain action
enters the same validated command boundary.

## Conceptual provenance and independence boundary

[MatrAIx](https://github.com/MatrAIx-ai/MatrAIx-Persona-8B) is credited as a source of conceptual
inspiration for several evaluation methods: constrained persona definitions, seeded and stratified
sampling, reproducible trials, task-specific verifiers, normalized trial output, and cohort-level
aggregation. TableTop DM reimplements the useful general ideas in its own architecture; it does not
integrate the MatrAIx application.

The boundary is explicit:

- no MatrAIx source code or runtime imports;
- no MatrAIx package, Git submodule, service, model, dataset, or schema dependency;
- no Harbor stack, MatrAIx frontend, or MatrAIx deployment component;
- no requirement to install or run MatrAIx;
- no claim that synthetic cohorts replace evidence from real people.

MatrAIx is primarily simulated-user evaluation infrastructure. TableTop DM is a persistent,
deterministic world kernel with tabletop, cognition, population, spatial-perception, and isolated
scenario domains. The attribution explains where some evaluation concepts came from without
implying shared code, shared runtime, or repository coupling.

## Required object separation

- A **user account** is a human login with profile data and global/world role grants.
- An **actor** is the world-scoped authority that proposes or observes simulation activity.
- A **PersonaBlueprint** is a versioned identity with dimensions, derived traits, provenance,
  and validation.
- An **EmbodiedEntity** is branch-scoped physical state such as location, health, inventory, and
  controller.
- A **MindState** holds an entity's mutable observations, beliefs, memories, relationships, and
  decision history.
- An **AgentRuntime** is the deterministic policy, planner, model provider, replay fixture, or
  human operator currently producing proposals.

Changing a runtime does not change the persona. An event becoming canonical does not make every
observer know it. Narration does not become state. A platform role does not implicitly grant
authority in every world.

Persona purpose separates an in-world `CHARACTER` from a `SIMULATED_PLAYTESTER`. A character's
compiled identity and trait prompts exclude tabletop/interface preferences and player onboarding
or GM relationships. Purpose is persistent and versioned; switching execution runtime never
changes it. This filter does not authorize arbitrary situation text or establish which lore a
character knows; trusted live context and knowledge-scoped retrieval remain separate boundaries.

Read-only character-context assembly now validates stored experience against the same branch's
source events and frozen physical grants. It cannot promote operator summaries into sensory
facts. The model-facing situation excludes ledger/controller/timeline metadata. Caller-authored
decision requests are restricted to privileged playtester evaluation; character requests fail
closed to caller-authored live situations; trusted proposals resolve pinned authored identity and
the server-owned movement catalog before deciding.

## Constitutional order

Character proposal generation is an operational read/decision path, never canonical mutation.
It accepts no client-authored fiction or candidate actions, resolves an exact CHARACTER binding,
requires actual body control and scoped command capabilities, and waits for dependent perception
projection. Immutable receipts/decision traces preserve server seeds and policy/context/catalog/
compiler/persona provenance. Retry keys are scoped by world/branch/run/body/actor.
Only normal command submission can apply the proposed action, after current kernel validation.
Proposal receipts are not execution leases and must never substitute for future controller epochs.
Policy advice is labeled CHARACTER_POLICY and cannot become human behavior ground truth.

Managed execution requires the current controller epoch and authority. HUMAN ownership and the
autonomous AGENT executor remain distinct. Autonomous proposals carry CHARACTER_POLICY authorship,
epoch, and expected step. The kernel validates inside the mutation lock, before the handler; one
transaction commits action/event/outbox and advances step/budget. Private handoff takes the same
lock and increments the epoch, fencing in-flight work. The API never upgrades old managed commands
by stamping a new epoch. No handoff is sensory. These controls apply to canonical LIVE runs;
complete campaign checkpoint/timeline restoration must eventually restore and fence them too.

1. A human, policy, planner, or model creates a typed `CommandProposal`.
2. The registry resolves a stable command contract and validates parameters.
3. The kernel checks actor identity, world/run/branch lineage, capabilities, entity control, and
   branch eligibility.
4. A deterministic handler returns a result and explicit state deltas.
5. Deltas commit atomically to one branch projection.
6. The command, result, resulting state hash, event, and outbox record are appended.
7. Observation, belief, memory, relationship, metrics, or narration may be derived afterward.

A rejected proposal leaves no partial state. Retrying the same actor/run/idempotency tuple
returns the original committed receipt.

## Acceptance properties

Optional dialogue generation proposes text only after policy action selection. Bounded network
and schema failures use deterministic fallback. Accepted text/model/prompt/source metadata freeze
in the existing private receipt before submission. Retries reuse that receipt. Speech carries
empty claims and cannot apply another action or world delta. No provider is active by default.

Guard consumes its defensive benefit once. Fixed spell invocation rechecks resource sufficiency,
range, sight, zone and capable targets inside the kernel transaction; rejection consumes no mana
or health. Migration 010 expands human choice kinds while preserving source/origin/RLS rules.

Speech/combat training records only accepted untraced human actions whose selected action existed
in the locked pre-command perceived catalog. Operator, stand-in and submitted-policy actions are
excluded. Attack evidence has physical event-time perception grants. Hidden or unprovoked bodies
are not autonomous melee targets; no candidate reads hidden armor, hit probability or health.
Basic attack parameters come from the server contract, never copied damage modifiers from history.
Context `character-context-1.2.0` orders known observations by canonical event sequence; provenance
remains private even when timestamps tie. Existing movement-profile versions remain readable.

Private human movement evidence commits atomically with its accepted source command, event and
outbox. Retries add neither another action nor another sample. Its input-origin field is independent
of controller authority; traced advice, autonomous executors, automation, rejected commands and
legacy unknown-origin records are excluded from human preference learning. Behavior provenance,
confidence and contradictions remain outside sensory payloads and model-facing situation text.
Profile reconstruction uses only the exact current world/branch/run/body/player/character. Complete
rewind of this evidence alongside all campaign state remains part of timeline revision work.

- Schema version + seed + fixed dimensions always produces the same valid persona.
- The same persona, policy, state, seed, and runtime assignment produces the same deterministic
  decision trace.
- Two observers may derive different beliefs from the same canonical event.
- Relationship changes retain immutable before/after vectors and a visible same-branch source
  event.
- Population cohorts are checked for feasibility and declared distribution tolerance.
- Population lifecycle transitions remain bound to their original world and branch after
  restart.
- Trial branches originate from immutable snapshots and cannot write canonical projections.
- Generic scenario jobs retain checkpoints, trial event envelopes, verifier facts, normalized
  metrics, and reports after restart.
- Calibration review and deployment promotion are separate actions.
- Public entity projections never expose secret state.
- Tactical, third-person, and first-person controls operate on the same commander, squad, weapon,
  health, enemy, and branch state; renderer frames remain perception-scoped.
- Synthetic outputs remain labeled hypotheses rather than evidence about real people.

## Supporting documentation

Character identity bindings are versioned controller configuration, like runtime assignments;
they do not mutate world truth, grant body control, or enter the sensory ledger. A binding pins
immutable authored content and a `CHARACTER` compiled profile to exact world/run/branch/entity
lineage and an existing mind. Rebinding preserves subjective history and runtime selection.
Authored starting claims stay outside canonical facts and learned evidence. Future autonomous
execution must resolve this binding and still submit authorized typed kernel proposals.

An accepted command's scene-refresh cursor is operational metadata, outside the character's
situation and evidence hash. Checking readiness reads the original event-time perception grant
and subjective projection; it does not resubmit the command, mutate a mind, recompute an audience
from current location, or expose canonical payloads. An unperceived action needs no fabricated
experience. Durable scene/context hydration is request-local and leaves projector caches intact.

- [Architecture and invariants](ARCHITECTURE.md)
- [Network and deployment diagram](NETWORK_AND_DEPLOYMENT.md)
- [Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md)
- [API and user workflows](API_AND_WORKFLOWS.md)
- [Operations](OPERATIONS.md)
- [Testing](TESTING.md)

The visual product direction is captured in
[the simulation-kernel concept](design/simulation-kernel-concept.png). The running React client
and typed API contracts are authoritative for interaction behavior.

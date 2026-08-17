# V2 simulation-kernel contract

TableTop DM v2 is a clean-break implementation of one domain-neutral simulation system with
three execution modes:

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
population, and evaluation code can operate without importing tabletop mechanics. Tabletop
commands enter the same validated mutation boundary as any future domain.

## Independence boundary

The repository contains no MatrAIx source, runtime import, submodule, service, or deployment
dependency. The rebuild adopts general methods—constrained persona generation, reproducible
sampling, task-specific verification, and aggregate comparison—and implements them locally for
a persistent-world architecture.

V1 is similarly outside the runtime boundary. It is retained only as a behavioral reference at
`v1-behavioral-reference-2026-08-17` (commit
`93e02846e4d73097afc65f2dfd684a8a7e49966b`); v2 has no compatibility data path. The frozen
tests, fixtures, and release bundle are inventoried in the
[Phase 0 behavioral-reference manifest](V1_BEHAVIORAL_REFERENCE.md).

## Required object separation

- A **PersonaBlueprint** is a versioned identity with dimensions, derived traits, provenance,
  and validation.
- An **EmbodiedEntity** is branch-scoped physical state such as location, health, inventory, and
  controller.
- A **MindState** holds an entity's mutable observations, beliefs, memories, relationships, and
  decision history.
- An **AgentRuntime** is the deterministic policy, planner, model provider, replay fixture, or
  human operator currently producing proposals.

Changing the runtime does not change the persona. An event becoming canonical does not make
every observer know it. Narration does not become state.

## Constitutional order

1. An actor or runtime creates a typed `CommandProposal`.
2. The command registry resolves a versioned contract.
3. Pydantic validates parameters.
4. Actor capabilities, embodied-entity control, world ownership, and branch kind are checked.
5. A deterministic handler returns a result and state deltas.
6. Deltas commit atomically to one branch projection.
7. The command, result, state hash, and event provenance are appended to the ledger.
8. An outbox record is written in the durable path.
9. Observation, belief, memory, metrics, or narration may be derived afterward.

A rejected proposal leaves no partial state. Retrying the same actor/run/idempotency tuple
returns the original receipt.

## Acceptance properties represented in code

- Schema version plus seed plus fixed persona dimensions produces the same valid blueprint.
- The same persona, compiled policy, starting state, and seed produces the same deterministic
  decision trace.
- Two observers can derive different beliefs from the same canonical event.
- Relationship changes retain immutable before/after vectors and a visible same-branch source
  event, so social state has causal history rather than an unaudited mutable score.
- Population cohorts are checked for feasibility before sampling and can be tested against
  declared distribution tolerances; materialized/active transitions remain bound to the pool's
  original world and branch across restart.
- Trial branches are created from immutable snapshot contents and preserve logical entity IDs.
- Trial execution is rejected if it reports a canonical-world mutation.
- Registered generic scenario definitions, job checkpoints, trial event envelopes, and normalized
  reports rehydrate from artifacts and PostgreSQL for continued inspection after restart.
- Calibration compares synthetic results with versioned human evidence without declaring the
  synthetic output to be human ground truth. Review and promotion are separate; promotion adds a
  deployable immutable registry version but does not select it for a runtime.
- Public entity projections never include secret state. Secret projection requires controller
  status or the same-world `entity.read.secret` capability.

## Supporting documentation

- [Architecture and invariants](ARCHITECTURE.md)
- [API and user workflows](API_AND_WORKFLOWS.md)
- [Operations, storage, migrations, and RLS](OPERATIONS.md)
- [Testing](TESTING.md)

The accepted visual direction is captured in
[the simulation-kernel concept](design/simulation-kernel-concept.png). The running React client
is the behavioral source of truth for interaction details.

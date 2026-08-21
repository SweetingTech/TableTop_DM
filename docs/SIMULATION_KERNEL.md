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

## Independence boundary

This repository contains no MatrAIx source, runtime import, submodule, service, or deployment
dependency. It independently implements broadly useful methods—constrained personas,
reproducible sampling, task-specific verification, and aggregate comparison—inside a persistent
world architecture.

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

## Constitutional order

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

- [Architecture and invariants](ARCHITECTURE.md)
- [Network and deployment diagram](NETWORK_AND_DEPLOYMENT.md)
- [Battlefield control modes and renderer hooks](BATTLEFIELD_CONTROL_AND_RENDERER_HOOKS.md)
- [API and user workflows](API_AND_WORKFLOWS.md)
- [Operations](OPERATIONS.md)
- [Testing](TESTING.md)

The visual product direction is captured in
[the simulation-kernel concept](design/simulation-kernel-concept.png). The running React client
and typed API contracts are authoritative for interaction behavior.

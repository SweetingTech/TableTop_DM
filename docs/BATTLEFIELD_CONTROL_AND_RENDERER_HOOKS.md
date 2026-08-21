# Battlefield control modes and renderer hooks

## Design objective

Tactical, third-person, and first-person play are different presentations and input schemes over
one battle simulation. They are not separate levels, encounters, pawns, inventories, or health
pools.

```text
                    Canonical BattleWorld
                            |
          +-----------------+-----------------+
          |                 |                 |
      Tactical          Third person      First person
      formation input   direct pawn input direct pawn input
      elevated camera   shoulder camera   head/weapon camera
          |                 |                 |
          +-----------------+-----------------+
                            |
            same entities, squad, weapons,
            health, enemies, objectives, ledger
```

The current repository implements the engine-neutral contracts and deterministic commands. It
does not embed Unity, Unreal, or another 3D runtime.

## Constitutional rules

1. A camera never owns or duplicates battle state.
2. Changing camera mode never respawns or replaces the commander entity.
3. Tactical and direct control consume the same weapon definition and upgrades.
4. Followers remain under squad AI while the commander is directly controlled.
5. Camera altitude or perspective never grants knowledge. Renderer frames contain only public
   entities authorized by perception and visibility policy.
6. Engine input becomes a typed command proposal; an external engine cannot mutate canonical
   state directly.
7. Switching modes is ledgered and replayable.

The fourth and fifth rules keep the feature compatible with spatially scoped knowledge. A player
may see a larger tactical composition without receiving enemies, dialogue, traps, or objectives
their character and squad could not perceive.

## Implemented contracts

The implementation lives in `domains/tabletop/battlefield/`.

### Camera and control authority

`CameraMode` supports:

- `TACTICAL`;
- `THIRD_PERSON`;
- `FIRST_PERSON`.

The simulation derives one of two control-authority modes:

- `FORMATION`: tactical input steers the formation;
- `DIRECT`: player input steers the commander pawn.

Third- and first-person modes both use direct authority. Their difference is presentation and
input mapping, not which canonical entity is controlled.

### Squad orders

The intentionally small order vocabulary is:

- `FOLLOW`;
- `HOLD`;
- `FOCUS`;
- `SPREAD`;
- `REGROUP`.

Orders are stored independently from camera mode in `tabletop.squad_orders`. Switching into or
out of direct control does not clear the order. `squad_ai` remains `ACTIVE`, so followers continue
operating while the player controls the leader.

### Unified weapons

`WeaponDefinition` contains the shared source stats:

```text
weapon_id, name, damage, fire_rate, range, magazine, reload_time,
recoil, spread, projectile_speed, penetration, squad_accuracy, asset_ref
```

`WeaponModifiers` resolves upgrades once into `ResolvedWeaponStats`. Aggregate squad combat uses
the same resolved damage, fire rate, penetration, and accuracy that direct control uses for
projectiles, recoil, spread, magazine, and reload behavior.

For example, a `1.25` fire-rate modifier changes both the command-view DPS contribution and the
direct-control rounds-per-second value. A renderer must not maintain a second upgrade table.

## Typed commands

The tabletop registry exposes:

```text
tabletop.battlefield.set_control_mode
tabletop.battlefield.issue_squad_order
```

Both require `action.propose` and `entity.control`, accept canonical or trial branches, and pass
through the normal branch commit authority check.

Example mode proposal parameters:

```json
{
  "camera_mode": "THIRD_PERSON"
}
```

Example squad order parameters:

```json
{
  "squad_id": "00000000-0000-4000-8000-000000000001",
  "order": "FOCUS",
  "target_entity_id": "00000000-0000-4000-8000-000000000002"
}
```

The mode command changes only `tabletop.control_modes`. The order command changes only
`tabletop.squad_orders`. Neither creates a new commander, squad, weapon, or enemy projection.

## Renderer bridge

`BattlefieldFrameBuilder` produces a versioned `BattlefieldFrame` containing:

- world, branch, run, projection version, and state hash;
- commander entity ID and public state;
- camera and control-authority mode;
- squad roster, formation, current order, and AI status;
- resolved weapon stats;
- authorized visible public entities.

The builder requires `visible_entity_ids` from the caller. There is deliberately no
"show everything" default. A perception/audience service, product authorization layer, or
privileged DM tool must decide which IDs are permitted before frame construction.

Two protocols define future integration points:

- `BattlefieldRendererPort.present(frame)` consumes an immutable authorized frame.
- `BattlefieldInputPort.poll()` returns renderer-neutral `BattlefieldControlInput` envelopes.

A future adapter should translate input envelopes into existing command proposals:

```text
engine input
    -> adapter validation and sequence check
    -> CommandProposal
    -> command bus / durable repository
    -> committed event and next state hash
    -> authorized BattlefieldFrame
    -> renderer
```

The adapter must never expose a mutable `BranchState`, database connection, secret entity state,
or unrestricted event ledger to the engine.

## Projection conventions

The bridge currently consumes these branch projections:

| Projection | Purpose |
| --- | --- |
| `tabletop.entities` | commander, soldiers, enemies, pickups, cover, objectives, and public combat state |
| `tabletop.squads` | leader, membership, and formation |
| `tabletop.control_modes` | camera mode, formation/direct authority, squad-AI status, revision |
| `tabletop.squad_orders` | current simple follower order and target, revision |
| `tabletop.weapons` | shared weapon definitions |

Future gates, projectiles, cover, objectives, and encounter-director state should remain ordinary
versioned projections and typed commands. They should not become engine-owned singleton state.

## External engine boundary

A future Unity or Unreal client can implement the two ports or consume an equivalent network
transport. The transport should eventually support:

- full authorized frame on connect/resync;
- ordered state/event deltas after a known state hash;
- client input sequence and idempotency keys;
- correlation/causation IDs for input -> command -> projectile/damage chains;
- fixed simulation ticks or declared authoritative timestamps;
- prediction metadata without client authority;
- asset references rather than engine prefabs in domain contracts;
- reconnect and hash-mismatch recovery.

Engine-specific concepts such as Pawn, CharacterMovement, NavMesh, animation blueprint, Mass
entity, prefab, or scene object belong in the adapter. They must not enter the neutral kernel or
become required Python dependencies.

## MVP acceptance test

The foundational test is represented at function level:

1. One commander has one canonical entity record, health pool, and weapon.
2. Two or more followers belong to one squad with AI active.
3. The player switches `TACTICAL -> THIRD_PERSON -> FIRST_PERSON -> TACTICAL`.
4. The same entity, HP, squad, weapon definition, and enemy state remain.
5. A squad `FOCUS` order remains active through camera changes.
6. Weapon modifiers resolve identically for aggregate and direct consumers.
7. The renderer frame excludes an enemy absent from the authorized visible-entity set.

This removes the primary architectural risk without pretending that camera animation, gun feel,
navigation, large-crowd rendering, or networking has already been implemented.

## Next implementation slices

1. Add a spatial perception/audience resolver that supplies frame visibility at event time.
2. Define gates, pickups, objectives, cover, and encounter-director projections and commands.
3. Add deterministic projectile, fire cadence, reload, and damage commands shared by both modes.
4. Add a lightweight squad policy that executes the five orders from observed information.
5. Prototype tactical/direct controls in the existing web client or a headless adapter.
6. Only then bind an external 3D engine through the renderer/input ports.

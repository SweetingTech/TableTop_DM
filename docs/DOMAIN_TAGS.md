# DOMAIN_TAGS
Status: Phase 3.2 canonical domain tag taxonomy and weighting model.

## Purpose
Domain tags classify committed `STATE_DELTA` and related ledger events so reputation, divine standing, faction response, and routing decisions remain deterministic.

## Canonical tag list (v1)
Only these tags may be emitted in `trace.domain_tags`.

### Combat
- `combat.attack`
- `combat.damage`
- `combat.heal`
- `combat.control`
- `combat.kill`
- `combat.spare`

### Social
- `social.persuade`
- `social.deceive`
- `social.intimidate`
- `social.assist`
- `social.insult`

### Moral / alignment-like behavior
- `virtue.mercy`
- `virtue.honor`
- `virtue.generosity`
- `vice.cruelty`
- `vice.greed`
- `vice.betrayal`

### World / economy / civic impact
- `world.stability_up`
- `world.stability_down`
- `economy.trade_gain`
- `economy.theft`
- `faction.support`
- `faction.hostility`

### Arcane / divine
- `arcane.ritual`
- `arcane.corruption`
- `divine.blessing`
- `divine.curse`
- `divine.oath_upheld`
- `divine.oath_broken`

## Routing implications
- Any `divine.*` tag triggers standing update evaluation for subscribed gods.
- `combat.kill` + `vice.cruelty` triggers bounty/retaliation policy checks.
- `economy.*` tags route to economy service for location metric updates.
- `faction.*` tags route to faction service conflict model.

## Validation requirements
- Tag list is closed-world; unknown tags are rejected at commit.
- Each `STATE_DELTA` must emit at least 1 and at most 5 domain tags.
- Tags must be deduplicated and sorted before persistence.

## Weight mapping config structure
Weights are additive deltas (`-100..100`) applied per domain event.

```json
{
  "contract_version": 1,
  "weights": {
    "god:ashen_judge": {
      "divine.oath_upheld": 12,
      "virtue.honor": 6,
      "vice.betrayal": -15,
      "vice.cruelty": -8
    },
    "god:moon_weaver": {
      "social.deceive": 5,
      "arcane.ritual": 10,
      "divine.oath_broken": -10
    },
    "faction:eclipse_wardens": {
      "world.stability_up": 8,
      "faction.support": 4,
      "economy.theft": -12,
      "combat.kill": -6
    }
  }
}
```

## Example tagging scenarios
- Player executes non-lethal takedown: `combat.attack`, `combat.spare`, `virtue.mercy`.
- God applies punitive curse after oath break: `divine.curse`, `divine.oath_broken`, `vice.betrayal`.
- Party protects caravan and restores market: `combat.damage`, `faction.support`, `economy.trade_gain`, `world.stability_up`.

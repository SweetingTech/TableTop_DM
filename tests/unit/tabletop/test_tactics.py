from __future__ import annotations

import pytest

from cognition.perception import PerceptionEngine, PerceptionProfile
from kernel.contracts import CommandProposal
from tests.unit.tabletop.test_spatial_epistemics import _world

pytestmark = pytest.mark.unit


def execute(fixture, command, parameters, key, *, listener=False):
    actor = fixture["actor"]
    body = fixture["speaker"]
    if listener:
        body = fixture["listener"]
        actor = actor.model_copy(
            update={
                "actor_id": fixture["listener_actor"],
                "controlled_entity_ids": frozenset({body}),
            }
        )
    return fixture["bus"].execute(
        CommandProposal(
            command_type=command,
            world_id=fixture["world"],
            branch_id=fixture["branch"],
            run_id=fixture["run"],
            actor_id=actor.actor_id,
            embodied_entity_id=body,
            parameters=parameters,
            idempotency_key=key,
            seed=1,
        ),
        actor,
    )


def prepared():
    fixture = _world()
    for body in fixture["state"].projections["tabletop.entities"].values():
        body.update({"hp": 12, "max_hp": 12, "armor": 10, "mana": 4})
    return fixture


def test_guard_adds_two_armor_for_one_attack_and_does_not_stack():
    fixture = prepared()
    execute(fixture, "tabletop.combat.guard", {}, "guard", listener=True)
    with pytest.raises(ValueError):
        execute(fixture, "tabletop.combat.guard", {}, "stack", listener=True)
    parameters = {"target_id": str(fixture["listener"]), "attack_bonus": 5}
    guarded = execute(fixture, "tabletop.combat.attack", parameters, "guarded")
    assert guarded.event.payload["attack_roll"] == 5 and not guarded.event.payload["hit"]
    ordinary = execute(fixture, "tabletop.combat.attack", parameters, "ordinary")
    assert ordinary.event.payload["hit"]


def test_legacy_attack_preserves_unguarded_projection_shape():
    fixture = prepared()
    target = fixture["state"].projections["tabletop.entities"][str(fixture["listener"])]
    before = dict(target)
    receipt = execute(
        fixture,
        "tabletop.combat.attack",
        {"target_id": str(fixture["listener"]), "attack_bonus": 5},
        "legacy-attack",
    )
    hp_after = receipt.event.payload["hp_after"]
    target = (
        fixture["bus"]
        .states.get(fixture["branch"])
        .projections["tabletop.entities"][str(fixture["listener"])]
    )
    assert target == {**before, "hp": hp_after, "defeated": hp_after == 0}
    assert "guarded" not in target


@pytest.mark.parametrize("failure", ["range", "invisible", "mana", "incapacitated", "zone"])
def test_spell_revalidates_live_state_and_rejects_without_consuming_mana(failure):
    fixture = prepared()
    state = fixture["state"]
    target = state.projections["tabletop.entities"][str(fixture["listener"])]
    caster = state.projections["tabletop.entities"][str(fixture["speaker"])]
    if failure == "range":
        target["x"] = 9
    elif failure == "zone":
        target["zone_id"] = "back"
    elif failure == "invisible":
        state.projections["tabletop.sensory_profiles"][str(fixture["listener"])]["invisible"] = True
    elif failure == "mana":
        caster["mana"] = 1
    else:
        target["hp"] = 0
    version = state.version
    mana = caster["mana"]
    with pytest.raises(ValueError):
        execute(
            fixture,
            "tabletop.magic.invoke",
            {"spell_id": "ARCANE_BOLT", "target_id": str(fixture["listener"])},
            "rejected",
        )
    assert state.version == version and caster["mana"] == mana


def test_spell_sound_witness_gets_no_participant_power_or_resource_details():
    fixture = prepared()
    fixture["state"].projections["tabletop.spatial.portals"][str(fixture["portal"])]["state"] = (
        "OPEN"
    )
    receipt = execute(
        fixture,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": str(fixture["listener"])},
        "spell",
    )
    grant = next(
        row for row in receipt.perceptions if row.observer_entity_id == fixture["back_room"]
    )
    observation = PerceptionEngine().observe(
        receipt.event,
        PerceptionProfile(
            observer_entity_id=fixture["back_room"], observer_actor_id=fixture["system_actor"]
        ),
        grant=grant,
    )
    assert observation.perceived_payload == {"summary": "Sounds of nearby spellcasting."}
    visible = next(
        row for row in receipt.perceptions if row.observer_entity_id == fixture["listener"]
    )
    observed = PerceptionEngine().observe(
        receipt.event,
        PerceptionProfile(
            observer_entity_id=fixture["listener"], observer_actor_id=fixture["listener_actor"]
        ),
        grant=visible,
    )
    assert observed.perceived_payload["power"] == 3
    assert "mana_after" not in observed.perceived_payload

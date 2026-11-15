from __future__ import annotations

import os
import uuid
from dataclasses import replace

import pytest
from pydantic import BaseModel, ConfigDict

from kernel.application import stable_id
from kernel.command_bus import CommandBus, CommandDefinition
from kernel.contracts import BranchKind, CommandResult, StateDelta
from kernel.errors import AuthorizationDenied
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene
from tests.unit.kernel.test_tactical_choices import resources
from tests.unit.tabletop.test_domain_commands import domain as domain
from tests.unit.tabletop.test_domain_commands import proposal

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("weapon", ["SPEAR", "SHORTSWORD"])
@pytest.mark.parametrize("copies", [1, 2])
def test_trade_reconciles_equipment_only_after_selling_final_copy(domain, weapon, copies):
    hero = domain["state"].projections["tabletop.entities"][str(domain["hero"])]
    hero.update({"equipped_weapon": weapon, "inventory": {weapon: copies}})
    request = proposal(
        domain,
        "tabletop.economy.trade",
        {
            "counterparty_id": str(domain["merchant"]),
            "item": weapon,
            "quantity": 1,
            "unit_price": 5,
            "direction": "SELL",
        },
        "sell-weapon",
    )
    receipt = domain["bus"].execute(request, domain["actor"])
    after = domain["state"].projections["tabletop.entities"][str(domain["hero"])]
    assert after["inventory"][weapon] == copies - 1
    assert after["equipped_weapon"] == ("UNARMED" if copies == 1 else weapon)
    assert domain["bus"].execute(request, domain["actor"]) == receipt
    assert after["gold"] == 55


def test_scene_and_context_remain_available_after_selling_equipped_weapon(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    sim, ids = app.extensions["simulation"], app.extensions["demo_ids"]
    body = sim.states.get(ids["branch_id"]).projections["tabletop.entities"][str(ids["hero_id"])]
    body.update({"equipped_weapon": "SPEAR", "inventory": {"SPEAR": 1}})
    client = app.test_client()
    client.environ_base["HTTP_X_TTDM_OPERATOR_TOKEN"] = os.environ["TTDM_OPERATOR_TOKEN"]
    base = {k: str(ids[k]) for k in ("world_id", "branch_id", "run_id")}
    response = client.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": str(ids["hero_id"]),
            "command_type": "tabletop.economy.trade",
            "parameters": {
                "counterparty_id": str(stable_id("demo:entity:merchant")),
                "item": "SPEAR",
                "quantity": 1,
                "unit_price": 5,
                "direction": "SELL",
            },
            "idempotency_key": "sell-last-spear",
        },
    )
    assert response.status_code == 200, response.get_json()
    path = f"/api/v2/worlds/{ids['world_id']}/branches/{ids['branch_id']}/entities/{ids['hero_id']}"
    scene = client.get(path + "/scene")
    assert scene.status_code == 200
    own = next(
        row
        for row in scene.get_json()["perceived_entities"]
        if row["entity_id"] == str(ids["hero_id"])
    )
    assert own["attack_reach"] == 1
    assert client.get(path + "/context").status_code == 200


def test_old_unavailable_equipment_does_not_block_scene_or_offer_impossible_melee(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"])
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    state.projections["tabletop.entities"][card["entity_id"]].update(
        {"equipped_weapon": "SPEAR", "inventory": {}}
    )
    provoke(admin, base, target, card, "old-loadout-threat")
    scene = player.get(path + "/scene")
    assert scene.status_code == 200
    own = next(
        row
        for row in scene.get_json()["perceived_entities"]
        if row["entity_id"] == card["entity_id"]
    )
    assert own["attack_reach"] == 0
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200
    assert context.get_json()["action_candidates"]
    assert all(
        c["command_type"] != "tabletop.combat.attack"
        for c in context.get_json()["action_candidates"]
    )


@pytest.mark.parametrize(
    "field,value",
    [("attack_bonus", 30), ("damage_dice", 20), ("damage_sides", 100), ("damage_bonus", 100)],
)
def test_action_cannot_supply_attack_rules_or_consume_a_failed_key(domain, field, value):
    before = domain["state"].state_hash
    request = proposal(
        domain,
        "tabletop.combat.attack",
        {"target_id": str(domain["enemy"]), field: value},
        "rules-tamper",
        seed=41,
    )
    with pytest.raises(ValueError, match="Invalid"):
        domain["bus"].execute(request, domain["actor"])
    assert domain["state"].state_hash == before
    valid = request.model_copy(update={"parameters": {"target_id": str(domain["enemy"])}})
    assert (
        domain["bus"].execute(valid, domain["actor"]).event.event_type == "tabletop.combat.attack"
    )


def test_weapon_stats_come_from_owned_equipment_and_body(domain):
    bodies = domain["state"].projections["tabletop.entities"]
    bodies[str(domain["hero"])].update(
        {"equipped_weapon": "SPEAR", "inventory": {"SPEAR": 1}, "attack_bonus": 5}
    )
    bodies[str(domain["enemy"])]["x"] = 3
    receipt = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.combat.attack",
            {"target_id": str(domain["enemy"])},
            "owned-spear",
            seed=41,
        ),
        domain["actor"],
    )
    assert receipt.result.result["weapon_id"] == "SPEAR"
    assert receipt.result.result["hit"] is True and 1 <= receipt.result.result["damage"] <= 8
    assert receipt.result.result["rules_version"] == "tabletop-action-rules-1.0.0"


@pytest.mark.parametrize(
    "fault", ["not_owned", "cross_zone", "wall", "invisible", "asleep", "stunned"]
)
def test_impossible_attack_has_no_effect(domain, fault):
    bodies = domain["state"].projections["tabletop.entities"]
    attacker, target = bodies[str(domain["hero"])], bodies[str(domain["enemy"])]
    if fault == "not_owned":
        attacker["equipped_weapon"] = "SPEAR"
    elif fault == "cross_zone":
        target["zone_id"] = "another-zone"
    elif fault == "wall":
        attacker.update({"equipped_weapon": "SPEAR", "inventory": {"SPEAR": 1}})
        target["x"] = 3
        domain["state"].projections["tabletop.obstacles"]["wall"] = {"x": 2, "y": 1}
    elif fault == "asleep":
        attacker["asleep"] = True
    elif fault == "invisible":
        domain["state"].projections["tabletop.sensory_profiles"] = {
            str(domain["enemy"]): {"invisible": True}
        }
    else:
        attacker["conditions"] = ["stunned"]
    before = domain["state"].state_hash
    with pytest.raises(ValueError):
        domain["bus"].execute(
            proposal(
                domain,
                "tabletop.combat.attack",
                {"target_id": str(domain["enemy"])},
                "impossible",
                seed=41,
            ),
            domain["actor"],
        )
    assert domain["state"].state_hash == before


@pytest.mark.parametrize("command", ["tabletop.magic.cast", "tabletop.magic.invoke"])
def test_cast_and_invoke_use_learned_fixed_rules_and_spend_once(domain, command):
    hero = domain["state"].projections["tabletop.entities"][str(domain["hero"])]
    hero.update({"hp": 10, "known_spells": ["MEND"]})
    request = proposal(
        domain, command, {"spell_id": "MEND", "target_id": str(domain["hero"])}, "mend"
    )
    receipt = domain["bus"].execute(request, domain["actor"])
    assert receipt.result.result["power"] == 4 and hero["hp"] == 10
    committed = domain["state"].projections["tabletop.entities"][str(domain["hero"])]
    assert committed["hp"] == 14 and committed["mana"] == 8
    assert domain["bus"].execute(request, domain["actor"]) == receipt
    assert committed["mana"] == 8


@pytest.mark.parametrize("command", ["tabletop.magic.cast", "tabletop.magic.invoke"])
@pytest.mark.parametrize(
    "field,value",
    [("power", 10000), ("mana_cost", 0), ("effect", "HEAL"), ("condition", "invisible")],
)
def test_cast_rules_cannot_be_authored_by_the_caller(domain, command, field, value):
    before = domain["state"].state_hash
    with pytest.raises(ValueError, match="Invalid"):
        domain["bus"].execute(
            proposal(
                domain,
                command,
                {"spell_id": "MEND", "target_id": str(domain["hero"]), field: value},
                "spell-tamper",
            ),
            domain["actor"],
        )
    assert domain["state"].state_hash == before


def test_unlearned_spell_is_not_granted_by_mana_or_public_availability(domain):
    hero = domain["state"].projections["tabletop.entities"][str(domain["hero"])]
    hero["known_spells"] = []
    before = domain["state"].state_hash
    with pytest.raises(ValueError, match="not learned"):
        domain["bus"].execute(
            proposal(
                domain,
                "tabletop.magic.invoke",
                {"spell_id": "ARCANE_BOLT", "target_id": str(domain["enemy"])},
                "unlearned",
            ),
            domain["actor"],
        )
    assert domain["state"].state_hash == before


def test_committed_old_schema_receipt_survives_stricter_command_upgrade(domain):
    class Legacy(BaseModel):
        legacy_rule: int

    class Current(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class Result(BaseModel):
        count: int

    def handler(command, state):
        return CommandResult(
            result={"count": 1},
            deltas=(
                StateDelta(projection="test.effects", operation="INCREMENT", values={"count": 1}),
            ),
        )

    original = CommandDefinition(
        "test.versioned",
        frozenset({"action.propose"}),
        frozenset({BranchKind.TRIAL}),
        handler,
        request_model=Legacy,
        result_model=Result,
    )
    older, newer = CommandBus(domain["bus"].states), CommandBus(domain["bus"].states)
    older.register(original)
    newer.register(replace(original, request_model=Current, version="2.0.0"))
    request = proposal(domain, "test.versioned", {"legacy_rule": 99}, "old-committed")
    receipt = older.execute(request, domain["actor"])
    assert newer.execute(request, domain["actor"]) == receipt
    assert domain["state"].projections["test.effects"]["singleton"]["count"] == 1
    with pytest.raises(ValueError):
        newer.execute(
            request.model_copy(update={"idempotency_key": "new-illegal"}), domain["actor"]
        )
    import uuid

    with pytest.raises(AuthorizationDenied):
        newer.execute(request.model_copy(update={"world_id": uuid.uuid4()}), domain["actor"])

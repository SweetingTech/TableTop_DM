import uuid

import pytest

from domains.tabletop import register_tabletop
from domains.tabletop.content_rating import ContentPolicy
from kernel.command_bus import CommandBus
from kernel.contracts import Actor, ActorKind, BranchKind, CommandProposal
from kernel.state import BranchState, InMemoryStateStore

pytestmark = pytest.mark.unit


@pytest.fixture
def domain():
    world, branch, run, actor_id, hero_id, enemy_id, merchant_id = [uuid.uuid4() for _ in range(7)]
    state = BranchState(
        world,
        branch,
        BranchKind.TRIAL,
        {
            "tabletop.entities": {
                str(hero_id): {
                    "x": 1,
                    "y": 1,
                    "hp": 20,
                    "max_hp": 20,
                    "armor": 12,
                    "mana": 10,
                    "gold": 50,
                    "inventory": {},
                },
                str(enemy_id): {
                    "x": 2,
                    "y": 1,
                    "hp": 12,
                    "max_hp": 12,
                    "armor": 10,
                    "mana": 0,
                    "gold": 0,
                    "inventory": {},
                },
                str(merchant_id): {
                    "x": 4,
                    "y": 4,
                    "hp": 10,
                    "max_hp": 10,
                    "armor": 10,
                    "mana": 0,
                    "gold": 100,
                    "inventory": {"herb": 5},
                },
            },
            "tabletop.obstacles": {"rock": {"x": 1, "y": 2}},
        },
    )
    store = InMemoryStateStore()
    store.add(state)
    actor = Actor(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        display_name="hero",
        capabilities=frozenset(
            {
                "action.propose",
                "entity.act",
                "entity.control",
                "faction.manage",
                "divine.invoke",
            }
        ),
        controlled_entity_ids=frozenset({hero_id}),
    )
    return {
        "world": world,
        "branch": branch,
        "run": run,
        "actor": actor,
        "hero": hero_id,
        "enemy": enemy_id,
        "merchant": merchant_id,
        "state": state,
        "bus": register_tabletop(CommandBus(store)),
    }


def proposal(domain, command_type, parameters, key, seed=None):
    return CommandProposal(
        command_type=command_type,
        world_id=domain["world"],
        branch_id=domain["branch"],
        run_id=domain["run"],
        actor_id=domain["actor"].actor_id,
        embodied_entity_id=domain["hero"],
        parameters=parameters,
        idempotency_key=key,
        seed=seed,
    )


def test_seeded_attack_is_deterministic_and_committed(domain):
    receipt = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.combat.attack",
            {"target_id": str(domain["enemy"])},
            "attack",
            seed=41,
        ),
        domain["actor"],
    )
    result = receipt.result.result
    assert result["attack_roll"] == 13
    assert result["hit"] is True
    committed_hp = domain["state"].projections["tabletop.entities"][str(domain["enemy"])]["hp"]
    assert committed_hp == result["hp_after"]


def test_blocked_movement_rolls_back(domain):
    before = domain["state"].state_hash
    with pytest.raises(ValueError, match="blocked"):
        domain["bus"].execute(
            proposal(domain, "tabletop.spatial.move", {"dx": 0, "dy": 1}, "move"),
            domain["actor"],
        )
    assert domain["state"].state_hash == before


def test_trade_conserves_gold_and_inventory(domain):
    entities = domain["state"].projections["tabletop.entities"]
    entities[str(domain["merchant"])].update({"x": 2, "y": 2})
    gold_before = entities[str(domain["hero"])]["gold"] + entities[str(domain["merchant"])]["gold"]
    offered = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.economy.configure_offer",
            {
                "maker_id": str(domain["merchant"]),
                "side": "SELL",
                "item": "herb",
                "quantity": 2,
                "unit_price": 5,
            },
            "herb-offer",
        ),
        domain["actor"],
    )
    domain["bus"].execute(
        proposal(
            domain,
            "tabletop.economy.trade",
            {
                "offer_id": offered.result.result["offer_id"],
                "quantity": 2,
            },
            "trade",
        ),
        domain["actor"],
    )
    committed = domain["state"].projections["tabletop.entities"]
    gold_after = committed[str(domain["hero"])]["gold"] + committed[str(domain["merchant"])]["gold"]
    assert gold_after == gold_before
    assert committed[str(domain["hero"])]["inventory"]["herb"] == 2
    assert committed[str(domain["merchant"])]["inventory"]["herb"] == 3


def test_every_tabletop_command_exposes_a_typed_contract(domain):
    contracts = domain["bus"].contracts()
    assert {contract["command_type"] for contract in contracts} == {
        "tabletop.battlefield.issue_squad_order",
        "tabletop.battlefield.set_control_mode",
        "tabletop.onboarding.act",
        "tabletop.console.submit",
        "tabletop.dialogue.speak",
        "tabletop.entity.spawn",
        "tabletop.entity.set_controllers",
        "tabletop.condition.apply",
        "tabletop.map.configure",
        "tabletop.spatial.move",
        "tabletop.combat.attack",
        "tabletop.combat.stabilize",
        "tabletop.rest.start",
        "tabletop.body.configure",
        "tabletop.equipment.equip",
        "tabletop.encounter.start",
        "tabletop.encounter.stop",
        "tabletop.resources.configure",
        "tabletop.combat.guard",
        "tabletop.clock.configure",
        "tabletop.clock.tick",
        "tabletop.clock.advance",
        "tabletop.activity.start",
        "tabletop.activity.cancel",
        "tabletop.weather.schedule",
        "tabletop.weather.cancel",
        "tabletop.population.bind",
        "tabletop.population.level",
        "tabletop.routine.configure",
        "tabletop.obligation.schedule",
        "tabletop.obligation.cancel",
        "tabletop.magic.cast",
        "tabletop.magic.invoke",
        "tabletop.economy.trade",
        "tabletop.economy.offer",
        "tabletop.economy.configure_offer",
        "tabletop.economy.withdraw_offer",
        "tabletop.economy.cancel_offer",
        "tabletop.faction.adjust_reputation",
        "tabletop.divine.bless",
        "tabletop.quest.advance",
        "tabletop.quest.configure",
        "tabletop.quest.accept",
        "tabletop.quest.claim",
        "tabletop.quest.cancel",
    }
    assert all(contract["request_schema"]["type"] == "object" for contract in contracts)
    assert all(contract["result_schema"]["type"] == "object" for contract in contracts)
    assert all(contract["result_schema"].get("properties") for contract in contracts)


def test_console_and_successful_movement(domain):
    dialogue = domain["bus"].execute(
        proposal(domain, "tabletop.console.submit", {"text": "  We parley.  "}, "dialogue"),
        domain["actor"],
    )
    assert dialogue.result.result == {
        "text": "We parley.",
        "submission_kind": "DIALOGUE",
        "interpreted": False,
        "summary": "We parley.",
    }
    moved = domain["bus"].execute(
        proposal(domain, "tabletop.spatial.move", {"dx": -1, "dy": 0}, "move-ok"),
        domain["actor"],
    )
    assert moved.result.result["destination"] == {"x": 0, "y": 1}
    assert domain["state"].projections["tabletop.entities"][str(domain["hero"])]["x"] == 0


def test_entity_spawn_keeps_private_metadata_out_of_public_receipts(domain):
    actor = domain["actor"].model_copy(
        update={"capabilities": domain["actor"].capabilities | {"entity.create"}}
    )
    entity_id = uuid.uuid4()
    receipt = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.entity.spawn",
            {
                "entity_id": str(entity_id),
                "name": "Quiet Informant",
                "entity_type": "NPC",
                "public_state": {"x": 5, "y": 2},
                "secret_state": {"allegiance": "hidden"},
                "controller_actor_id": str(actor.actor_id),
            },
            "spawn-private",
        ),
        actor,
    )
    assert receipt.result.entity_mutations[0].secret_state == {"allegiance": "hidden"}
    assert "entity_mutations" not in receipt.result.model_dump(mode="json")
    projected = domain["state"].projections["tabletop.entities"][str(entity_id)]
    assert projected == {
        "name": "Quiet Informant",
        "entity_type": "NPC",
        "x": 5,
        "y": 2,
    }


@pytest.mark.parametrize(
    ("spell_id", "effect", "expected"),
    (
        ("ARCANE_BOLT", "DAMAGE", {"hp": 9}),
        ("MEND", "HEAL", {"hp": 12}),
    ),
)
def test_magic_effects_are_deterministic_and_spend_mana(domain, spell_id, effect, expected):
    if effect == "HEAL":
        domain["state"].projections["tabletop.entities"][str(domain["enemy"])]["hp"] = 8
    parameters = {
        "target_id": str(domain["enemy"]),
        "spell_id": spell_id,
    }
    receipt = domain["bus"].execute(
        proposal(domain, "tabletop.magic.cast", parameters, f"magic-{effect}"),
        domain["actor"],
    )
    entities = domain["state"].projections["tabletop.entities"]
    assert entities[str(domain["hero"])]["mana"] == 8
    assert {key: entities[str(domain["enemy"])][key] for key in expected} == expected
    assert receipt.result.result["effect"] == effect


def test_failed_magic_rolls_back_mana_and_target(domain):
    domain["state"].projections["tabletop.entities"][str(domain["hero"])]["mana"] = 1
    before = domain["state"].state_hash
    with pytest.raises(ValueError, match="insufficient mana"):
        domain["bus"].execute(
            proposal(
                domain,
                "tabletop.magic.cast",
                {
                    "target_id": str(domain["enemy"]),
                    "spell_id": "ARCANE_BOLT",
                },
                "magic-fail",
            ),
            domain["actor"],
        )
    assert domain["state"].state_hash == before


def test_faction_divine_and_quest_updates_are_replayable(domain):
    faction = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.faction.adjust_reputation",
            {"faction_id": "harbor-watch", "amount": 100, "reason": "Saved the quay"},
            "faction",
        ),
        domain["actor"],
    )
    blessing = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.divine.bless",
            {"target_id": str(domain["hero"]), "blessing": "Tideward", "duration_turns": 3},
            "blessing",
        ),
        domain["actor"],
    )
    # Quest progress is a physical outcome rather than a caller-authored counter.
    domain["state"].projections["tabletop.entities"][str(domain["merchant"])].update(x=2, y=2)
    offered = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.quest.configure",
            {
                "giver_id": str(domain["merchant"]),
                "title": "Reach the road",
                "description": "Walk to the road.",
                "objectives": [
                    {"kind": "MOVE", "description": "Reach road", "x": 2, "y": 1},
                ],
            },
            "quest-offer",
        ),
        domain["actor"],
    )
    quest_id = offered.result.result["quest_id"]
    domain["bus"].execute(
        proposal(domain, "tabletop.quest.accept", {"quest_id": quest_id}, "accept"), domain["actor"]
    )
    domain["bus"].execute(
        proposal(domain, "tabletop.spatial.move", {"dx": 1, "dy": 0}, "road"), domain["actor"]
    )
    quest = domain["bus"].execute(
        proposal(
            domain,
            "tabletop.quest.advance",
            {"quest_id": quest_id},
            "quest",
        ),
        domain["actor"],
    )
    assert faction.result.result["after"] == 100
    assert blessing.result.result["duration_turns"] == 3
    assert quest.result.result["status"] == "READY"
    assert (
        domain["state"].projections["tabletop.reputation"][str(domain["hero"])]["factions"][
            "harbor-watch"
        ]
        == 100
    )


def test_onboarding_records_invalid_help_loop_and_completion(domain):
    actions = (
        "WRONG",
        "ASK_HELP",
        "ASK_HELP",
        "START",
        "READ_INSTRUCTIONS",
        "COMPLETE_FIRST_GOAL",
        "CLAIM_REWARD",
        "CHOOSE_PATH",
        "FINISH_ONBOARDING",
    )
    for index, action in enumerate(actions):
        domain["bus"].execute(
            proposal(domain, "tabletop.onboarding.act", {"action": action}, f"onboard-{index}"),
            domain["actor"],
        )
    record = domain["state"].projections["tabletop.onboarding"][str(domain["hero"])]
    assert record["invalid_actions"] == 1
    assert record["help_requests"] == 2
    assert record["dialogue_loops"] == 1
    assert record["completed"] is True


def test_content_policy_is_deterministic_and_reports_matched_boundaries():
    policy = ContentPolicy(("graphic torture", "slur-placeholder"))
    allowed = policy.evaluate("A tense but safe negotiation", rating="TEEN")
    blocked = policy.evaluate("The prompt asks for GRAPHIC TORTURE", rating="MATURE")
    assert allowed.allowed is True
    assert blocked.allowed is False
    assert blocked.rating == "MATURE"
    assert blocked.matched_boundaries == ("graphic torture",)

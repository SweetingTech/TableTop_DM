from __future__ import annotations

import random
import uuid

import pytest
from pydantic import BaseModel, ConfigDict

from domains.tabletop.rules import attack_profile
from kernel.command_bus import CommandDefinition
from kernel.contracts import ActorKind, BranchKind, CommandResult, StateDelta
from tests.unit.kernel.test_action_time_api import advance_clock
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_tactical_choices import command
from tests.unit.kernel.test_world_time import api_command, clock_game
from tests.unit.tabletop.test_domain_commands import domain as domain_fixture
from tests.unit.tabletop.test_domain_commands import proposal

pytestmark = pytest.mark.unit


class OwnedItems(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: uuid.UUID


def grant_items(app, admin, base, entity_id):
    """Test-only typed provisioning through the real atomic, authorized kernel."""

    def apply(proposal, state):
        request = OwnedItems.model_validate(proposal.parameters)
        return CommandResult(
            result={"provisioned": True},
            deltas=(
                StateDelta(
                    projection="tabletop.entities",
                    operation="MERGE",
                    entity_id=request.entity_id,
                    values={"inventory": {"SPEAR": 1, "SHORTSWORD": 1}},
                ),
            ),
            domain_tags=("operator",),
        )

    bus = app.extensions["simulation"].bus
    if "test.owned_items" not in {row["command_type"] for row in bus.contracts()}:
        bus.register(
            CommandDefinition(
                "test.owned_items",
                frozenset({"entity.control"}),
                frozenset({BranchKind.CANONICAL}),
                apply,
                request_model=OwnedItems,
            )
        )
    api_command(admin, base, "test.owned_items", {"entity_id": entity_id}, "owned-items")


def configure_body(admin, base, entity_id, key="body-profile", **changes):
    parameters = {
        "entity_id": entity_id,
        "ability_scores": {"strength": 18, "dexterity": 20},
        "proficiency_bonus": 2,
        "trained_weapons": ["UNARMED", "SHORTSWORD", "SPEAR"],
        **changes,
    }
    return api_command(admin, base, "tabletop.body.configure", parameters, key)


def prepare_combat(app, game=None):
    game = game or clock_game(app)
    admin, player, card, path, run, target, base = game
    grant_items(app, admin, base, card["entity_id"])
    configure_body(admin, base, card["entity_id"])
    return game


@pytest.mark.parametrize(
    "weapon,trained,bonus,damage,ability",
    [
        ("UNARMED", True, 6, 4, "strength"),
        ("SPEAR", True, 6, 4, "strength"),
        ("SHORTSWORD", True, 7, 5, "dexterity"),
        ("SHORTSWORD", False, 5, 5, "dexterity"),
    ],
)
def test_ability_training_and_finesse_override_stale_flat_body_bonuses(
    weapon, trained, bonus, damage, ability
):
    profile = attack_profile(
        {
            "ability_scores": {"strength": 18, "dexterity": 20},
            "proficiency_bonus": 2,
            "trained_weapons": [weapon] if trained else [],
            "inventory": {weapon: 1},
            "equipped_weapon": weapon,
            "attack_bonus": 30,
            "damage_bonus": 100,
            "conditions": ["poisoned"],
        }
    )
    assert (profile.attack_bonus, profile.damage_bonus, profile.ability) == (bonus, damage, ability)
    assert profile.proficiency_bonus == (2 if trained else 0) and profile.disadvantage


def test_legacy_explicit_body_profile_is_preserved_without_guessing_card_stats():
    profile = attack_profile({"attack_bonus": 4, "damage_bonus": 2})
    assert profile.attack_bonus == 4 and profile.damage_bonus == 2 and profile.ability is None


@pytest.mark.parametrize(
    "changes",
    [
        {"ability_scores": {"strength": 31}},
        {"attack_bonus": 30},
        {"equipped_weapon": "LASER"},
        {"equipped_weapon": "SPEAR"},
        {"hp": 999},
        {"known_spells": ["FORBIDDEN"]},
    ],
)
def test_manager_configuration_cannot_supply_arbitrary_stats_resources_or_unowned_gear(
    monkeypatch, tmp_path, changes
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "tabletop.body.configure",
            "idempotency_key": "bad-profile",
            "parameters": {"entity_id": card["entity_id"], "ability_scores": {}, **changes},
        },
    )
    assert response.status_code == 400, response.get_json()
    assert (state.state_hash, state.version) == before


def test_equip_uses_owned_gear_and_actual_seeded_damage_live_sheet_and_late_config_retry(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    game = prepare_combat(app)
    admin, player, card, path, run, target, base = game
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    hp_before = state.projections["tabletop.entities"][target]["hp"]
    equip = command(
        player, base, card, "tabletop.equipment.equip", {"weapon_id": "SHORTSWORD"}, "equip"
    )
    assert equip.status_code == 200, equip.get_json()
    mark = state.state_hash, state.version
    assert (
        command(
            player, base, card, "tabletop.equipment.equip", {"weapon_id": "SHORTSWORD"}, "equip"
        ).get_json()
        == equip.get_json()
    )
    assert (state.state_hash, state.version) == mark
    advance_clock(admin, base, 6)
    hit = command(player, base, card, "tabletop.combat.attack", {"target_id": target}, "attack")
    assert hit.status_code == 200, hit.get_json()
    result = hit.get_json()["result"]["result"]
    assert (
        result["ability"] == "dexterity"
        and result["attack_bonus"] == 7
        and result["damage_bonus"] == 5
    )
    rng = random.Random(result["randomness"]["action_seed"])
    roll = rng.randint(1, 20)
    assert result["attack_roll"] == roll
    expected = rng.randint(1, 6) + 5 if result["hit"] else 0
    assert result["damage"] == expected and result["hp_after"] == max(0, hp_before - expected)
    view = player.get(f"/api/v2/player/characters/{card['character_id']}/live-state").get_json()[
        "body"
    ]
    assert view["ability_scores"]["dexterity"] == 20 and view["attack_bonus"] == 7
    before = state.state_hash, state.version
    configure_body(admin, base, card["entity_id"])
    assert (state.state_hash, state.version) == before
    assert (
        state.projections["tabletop.entities"][card["entity_id"]]["equipped_weapon"] == "SHORTSWORD"
    )
    stored = next(
        row
        for row in player.get("/api/v2/player/characters").get_json()["items"]
        if row["character_id"] == card["character_id"]
    )
    assert stored == card
    context = player.get(path + "/context", query_string={"run_id": run})
    assert context.status_code == 200, context.get_json()
    situation = str(context.get_json()["situation"])
    assert "A shortsword was readied." in situation
    assert "tabletop.equipment.equip" not in situation


@pytest.mark.parametrize(
    "kind,parameters,expected",
    [
        ("tabletop.body.configure", {"ability_scores": {"strength": 30}}, 403),
        ("tabletop.equipment.equip", {"weapon_id": "SPEAR", "damage_bonus": 100}, 400),
        ("tabletop.equipment.equip", {"weapon_id": "LASER"}, 400),
        ("tabletop.equipment.equip", {"weapon_id": "SPEAR"}, 400),
    ],
)
def test_unowned_forged_and_player_configured_gear_have_no_writes(
    monkeypatch, tmp_path, kind, parameters, expected
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = clock_game(app)
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    before = state.state_hash, state.version
    if kind == "tabletop.body.configure":
        parameters = {"entity_id": card["entity_id"], **parameters}
    response = command(player, base, card, kind, parameters, "forged")
    assert response.status_code == expected, response.get_json()
    assert (state.state_hash, state.version) == before


@pytest.mark.parametrize("actor_kind", [ActorKind.HUMAN, ActorKind.AGENT])
def test_same_derived_weapon_rules_and_equip_ownership_in_trials(actor_kind):
    domain = domain_fixture.__wrapped__()
    actor = domain["actor"].model_copy(update={"kind": actor_kind})
    domain["state"].projections["tabletop.entities"][str(domain["hero"])]["inventory"] = {
        "SHORTSWORD": 1
    }
    body = proposal(
        domain,
        "tabletop.body.configure",
        {"entity_id": domain["hero"], "ability_scores": {"strength": 12, "dexterity": 18}},
        "config",
    )
    domain["bus"].execute(body, actor)
    request = proposal(domain, "tabletop.equipment.equip", {"weapon_id": "SHORTSWORD"}, "equip")
    receipt = domain["bus"].execute(request, actor)
    assert domain["bus"].execute(request, actor) == receipt
    attack = domain["bus"].execute(
        proposal(
            domain, "tabletop.combat.attack", {"target_id": domain["enemy"]}, "attack", seed=41
        ),
        actor,
    )
    assert attack.result.result["attack_bonus"] == 6 and attack.result.result["damage_bonus"] == 4

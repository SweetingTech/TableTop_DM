from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

from domains.tabletop.rules import DEFAULT_SPELLS, SpellId
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandResult, StateDelta
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene

pytestmark = pytest.mark.unit


class Resources(BaseModel):
    entity_id: uuid.UUID
    hp: int = 5
    mana: int = 8
    known_spells: tuple[SpellId, ...] = DEFAULT_SPELLS


def resources(app, admin, base, entity, hp=5, mana=8, known_spells=DEFAULT_SPELLS):
    """Test-only typed setup, exercising the real kernel transaction in both stores."""

    def change(proposal, state):
        request = Resources.model_validate(proposal.parameters)
        return CommandResult(
            result={"ready": True},
            deltas=(
                StateDelta(
                    projection="tabletop.entities",
                    operation="MERGE",
                    entity_id=request.entity_id,
                    values={
                        "hp": request.hp,
                        "max_hp": 12,
                        "mana": request.mana,
                        "armor": 10,
                        "known_spells": list(request.known_spells),
                    },
                ),
            ),
        )

    bus = app.extensions["simulation"].bus
    if "test.resources" not in {row["command_type"] for row in bus.contracts()}:
        bus.register(
            CommandDefinition(
                command_type="test.resources",
                required_capabilities=frozenset({"entity.control"}),
                allowed_branch_kinds=frozenset({BranchKind.CANONICAL}),
                handler=change,
                request_model=Resources,
            )
        )
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "command_type": "test.resources",
            "parameters": {
                "entity_id": entity,
                "hp": hp,
                "mana": mana,
                "known_spells": list(known_spells),
            },
            "idempotency_key": "resources-" + uuid.uuid4().hex,
        },
    )
    assert response.status_code == 200, response.get_json()


def command(player, base, card, kind, parameters, key):
    return player.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": card["entity_id"],
            "command_type": kind,
            "parameters": parameters,
            "idempotency_key": key,
        },
    )


def leave_and_run(app, player, path, run, key):
    response = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 1,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200, response.get_json()
    assert app.extensions["character_runner"].run_once() == 1
    return list(app.extensions["simulation"].events.values())[-1]


def establish_helper(app, admin, base, card):
    response = admin.post(
        f"/api/v2/worlds/{base['world_id']}/entities",
        json={
            "world_id": base["world_id"],
            "branch_id": base["branch_id"],
            "name": "Traveling healer",
            "entity_type": "NPC",
            "controller_actor_id": str(app.extensions["demo_ids"]["actor_id"]),
            "public_state": {"x": 0, "y": 1, "hp": 5, "max_hp": 12, "mana": 4},
        },
    )
    assert response.status_code == 201, response.get_json()
    helper = response.get_json()["entity_id"]
    resources(app, admin, base, card["entity_id"])
    response = command(
        admin,
        base,
        {"entity_id": helper},
        "tabletop.magic.invoke",
        {"spell_id": "MEND", "target_id": card["entity_id"]},
        "help-witnessed",
    )
    assert response.status_code == 200, response.get_json()
    resources(app, admin, base, card["entity_id"])
    return helper


def record_support_choices(app, admin, player, base, card, helper, target):
    sources = set()
    for index in range(4):
        response = command(
            player,
            base,
            card,
            "tabletop.magic.invoke",
            {"spell_id": "MEND", "target_id": target},
            f"heal-preference-{index}",
        )
        assert response.status_code == 200, response.get_json()
        sources.add(response.get_json()["event"]["event_id"])
        resources(app, admin, base, card["entity_id"])
        if target == helper:
            resources(app, admin, base, helper)
    return sources


def test_comparable_aid_choices_can_override_injured_self_priority(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, stranger, base = setup_scene(app)
    helper = establish_helper(app, admin, base, card)
    resources(app, admin, base, stranger)
    before = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    own_key, help_key = f"spell:MEND:{card['entity_id']}", f"spell:MEND:{helper}"
    assert before["action_scores"][own_key] > before["action_scores"][help_key]
    assert f"spell:MEND:{stranger}" not in before["action_scores"]

    sources = record_support_choices(app, admin, player, base, card, helper, helper)
    resources(app, admin, base, card["entity_id"], hp=12)
    healthy = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert healthy["comparable_count"] == 0
    assert own_key not in healthy["action_scores"]
    resources(app, admin, base, card["entity_id"])
    profile = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert set(profile["evidence_event_ids"]) == sources
    assert profile["action_scores"][help_key] > profile["action_scores"][own_key]
    event = leave_and_run(app, player, path, run, "return-the-help")
    assert event.event_type == "tabletop.magic.invoke" and event.payload["target_id"] == helper
    assert set(app.extensions["simulation"].human_decision_evidence) == {
        uuid.UUID(event_id) for event_id in sources
    }


def test_perceived_attacker_is_no_longer_a_support_target(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, _, base = setup_scene(app)
    helper = establish_helper(app, admin, base, card)
    provoke(admin, base, helper, card, "helper-turns-hostile")
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    assert any(
        row["command_type"] == "tabletop.combat.attack" and row["parameters"]["target_id"] == helper
        for row in context["action_candidates"]
    )
    assert not any(
        row["parameters"].get("spell_id") == "MEND" and row["parameters"]["target_id"] == helper
        for row in context["action_candidates"]
    )


def test_injured_body_heals_with_fixed_cost_and_power_through_runner(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"])
    provoke(admin, base, target, card, "attacked")
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    spell = next(
        row for row in context["action_candidates"] if row["parameters"].get("spell_id") == "MEND"
    )
    assert set(spell["parameters"]) == {"spell_id", "target_id"}
    event = leave_and_run(app, player, path, run, "heal")
    assert event.event_type == "tabletop.magic.invoke" and event.payload["spell_id"] == "MEND"
    assert event.payload["power"] == 4 and event.payload["mana_after"] == 6
    own = player.get(path + "/scene").get_json()
    body = next(row for row in own["perceived_entities"] if row["entity_id"] == card["entity_id"])
    assert body["health"] == 9 and body["mana"] == 6
    assert not any(
        row.get("choices") for row in app.extensions["simulation"].human_decision_evidence.values()
    )


def test_guard_history_drives_runner_and_next_attack_consumes_guard(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], hp=12, mana=0)
    for index in range(4):
        provoke(admin, base, target, card, f"attack-{index}")
        response = command(player, base, card, "tabletop.combat.guard", {}, f"guard-{index}")
        assert response.status_code == 200, response.get_json()
        assert (
            command(player, base, card, "tabletop.combat.guard", {}, f"guard-{index}").get_json()
            == response.get_json()
        )
    provoke(admin, base, target, card, "attack-final")
    profile = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert profile["comparable_count"] == 4
    event = leave_and_run(app, player, path, run, "guard")
    assert event.event_type == "tabletop.combat.guard"
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    assert state.projections["tabletop.entities"][card["entity_id"]]["guarded"]
    provoke(admin, base, target, card, "consume")
    assert not state.projections["tabletop.entities"][card["entity_id"]]["guarded"]


def test_an_unoffered_choice_keeps_its_pinned_fallback(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], hp=9)
    provoke(admin, base, target, card, "first-threat")
    fallback = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    own_heal, attack = f"spell:MEND:{card['entity_id']}", f"attack:{target}"

    resources(app, admin, base, card["entity_id"], hp=12)
    for index in range(3):
        result = command(player, base, card, "tabletop.combat.guard", {}, f"prefer-guard-{index}")
        assert result.status_code == 200, result.get_json()
        provoke(admin, base, target, card, f"consume-guard-{index}")
    resources(app, admin, base, card["entity_id"], hp=9)
    learned = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert learned["comparable_count"] == 3
    assert learned["action_sample_counts"][own_heal] == 0
    assert learned["action_scores"][own_heal] == fallback["action_scores"][own_heal]
    assert learned["action_sample_counts"][attack] == 3
    assert learned["action_scores"][attack] < fallback["action_scores"][attack]
    assert learned["action_scores"]["guard"] > fallback["action_scores"]["guard"]


@pytest.mark.parametrize(
    "parameters",
    [
        {"spell_id": "MEND", "power": 999},
        {"spell_id": "MEND", "mana_cost": 0},
        {"spell_id": "UNKNOWN"},
    ],
)
def test_spell_caller_cannot_invent_effects_or_costs(monkeypatch, tmp_path, parameters):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, _, _, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"])
    response = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {"target_id": card["entity_id"], **parameters},
        "invalid",
    )
    assert response.status_code == 400


def test_known_threat_bolt_and_private_own_resource_visibility(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], hp=12, mana=4)
    before = player.get(path + "/context", query_string={"run_id": run}).get_json()
    assert not any(
        row["command_type"] == "tabletop.magic.invoke" for row in before["action_candidates"]
    )
    provoke(admin, base, target, card, "attacked")
    response = command(
        player,
        base,
        card,
        "tabletop.magic.invoke",
        {"spell_id": "ARCANE_BOLT", "target_id": target},
        "bolt",
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event"]["payload"]["mana_after"] == 2
    scene = player.get(path + "/scene").get_json()
    assert all(
        row["mana"] is None
        for row in scene["perceived_entities"]
        if row["entity_id"] != card["entity_id"]
    )


@pytest.mark.parametrize("mana", [6, -1])
def test_explicit_card_mana_is_validated_before_roster_mutation(monkeypatch, tmp_path, mana):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, _, _, base = setup_scene(app)
    created = player.post(
        "/api/v2/player/characters",
        json={"world_id": base["world_id"], "name": "Resource traveler", "sheet": {"mana": mana}},
    )
    assert created.status_code == 201, created.get_json()
    new_card = created.get_json()
    game = admin.post(
        "/api/v2/dm/games", json={"world_id": base["world_id"], "name": "Resources"}
    ).get_json()
    response = admin.put(
        f"/api/v2/dm/games/{game['game_id']}/members",
        json={
            "user_id": card["owner_user_id"],
            "character_id": new_card["character_id"],
            "membership_role": "PLAYER",
        },
    )
    assert response.status_code == (200 if mana >= 0 else 400), response.get_json()
    if mana >= 0:
        saved = next(
            row
            for row in player.get("/api/v2/player/characters").get_json()["items"]
            if row["character_id"] == new_card["character_id"]
        )
        state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
        assert state.projections["tabletop.entities"][saved["entity_id"]]["mana"] == mana
    else:
        games = admin.get("/api/v2/games").get_json()["items"]
        assert not next(row for row in games if row["game_id"] == game["game_id"])["members"]


@pytest.mark.parametrize("learned", [(), ("MEND",)])
def test_body_spell_knowledge_limits_choices_and_is_private_to_self(monkeypatch, tmp_path, learned):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    resources(app, admin, base, card["entity_id"], known_spells=learned)
    provoke(admin, base, target, card, "spell-knowledge-threat")
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    spell_ids = {
        row["parameters"]["spell_id"]
        for row in context["action_candidates"]
        if row["command_type"] == "tabletop.magic.invoke"
    }
    assert spell_ids == set(learned)
    scene = player.get(path + "/scene").get_json()
    for row in scene["perceived_entities"]:
        assert row["known_spell_ids"] == (
            list(learned) if row["entity_id"] == card["entity_id"] else None
        )


@pytest.mark.parametrize(
    "learned, valid", [(["MEND"], True), (["UNKNOWN"], False), ("MEND", False)]
)
def test_card_spell_knowledge_is_validated_before_roster_mutation(
    monkeypatch, tmp_path, learned, valid
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, _, _, base = setup_scene(app)
    created = player.post(
        "/api/v2/player/characters",
        json={
            "world_id": base["world_id"],
            "name": "Apprentice",
            "sheet": {"mana": 8, "known_spells": learned},
        },
    )
    assert created.status_code == 201
    new_card = created.get_json()
    game = admin.post(
        "/api/v2/dm/games", json={"world_id": base["world_id"], "name": "Apprentice game"}
    ).get_json()
    response = admin.put(
        f"/api/v2/dm/games/{game['game_id']}/members",
        json={
            "user_id": card["owner_user_id"],
            "character_id": new_card["character_id"],
            "membership_role": "PLAYER",
        },
    )
    assert response.status_code == (200 if valid else 400), response.get_json()
    if valid:
        saved = next(
            c
            for c in player.get("/api/v2/player/characters").get_json()["items"]
            if c["character_id"] == new_card["character_id"]
        )
        body = (
            app.extensions["simulation"]
            .states.get(uuid.UUID(base["branch_id"]))
            .projections["tabletop.entities"][saved["entity_id"]]
        )
        assert body["known_spells"] == learned
        assert (
            player.patch(
                f"/api/v2/player/characters/{new_card['character_id']}",
                json={"sheet": {"mana": 999, "known_spells": ["ARCANE_BOLT", "MEND"]}},
            ).status_code
            == 200
        )
        assert (
            admin.put(
                f"/api/v2/dm/games/{game['game_id']}/members",
                json={
                    "user_id": card["owner_user_id"],
                    "character_id": new_card["character_id"],
                    "membership_role": "PLAYER",
                },
            ).status_code
            == 200
        )
        body = (
            app.extensions["simulation"]
            .states.get(uuid.UUID(base["branch_id"]))
            .projections["tabletop.entities"][saved["entity_id"]]
        )
        assert body["known_spells"] == learned and body["mana"] == 8
    else:
        games = admin.get("/api/v2/games").get_json()["items"]
        assert not next(row for row in games if row["game_id"] == game["game_id"])["members"]

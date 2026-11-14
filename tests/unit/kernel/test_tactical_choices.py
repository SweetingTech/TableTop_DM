from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandResult, StateDelta
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_speech_combat_behavior import provoke, setup_scene

pytestmark = pytest.mark.unit


class Resources(BaseModel):
    entity_id: uuid.UUID
    hp: int = 5
    mana: int = 8


def resources(app, admin, base, entity, hp=5, mana=8):
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
                    values={"hp": request.hp, "max_hp": 12, "mana": request.mana, "armor": 10},
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
            "parameters": {"entity_id": entity, "hp": hp, "mana": mana},
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

from __future__ import annotations

import uuid

import pytest

from cognition.choices import choice_profile, weighted_choices
from cognition.context import CharacterContext
from cognition.engine import DecisionAction, DecisionRequest, LayeredDecisionEngine
from cognition.models import Observation
from domains.tabletop.character_history import CharacterCardContent
from domains.tabletop.spatial.scene import PerceivedScene
from persona.models import CompiledPersona, PersonaPurpose
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def setup_scene(app, *, scope=None):
    admin, player, card, game, path, run, user = setup_bound_character(app, scope=scope)
    branch = path.split("/")[6]
    actor = app.extensions["demo_ids"]["actor_id"]
    response = admin.post(
        f"/api/v2/worlds/{card['world_id']}/entities",
        json={
            "world_id": card["world_id"],
            "branch_id": branch,
            "name": "Nearby speaker",
            "entity_type": "NPC",
            "controller_actor_id": str(actor),
            "public_state": {"x": 1, "y": 0, "hp": 100, "max_hp": 100, "armor": 100, "reach": 1},
        },
    )
    assert response.status_code == 201, response.get_json()
    target = response.get_json()["entity_id"]
    base = {"world_id": card["world_id"], "branch_id": branch, "run_id": run}
    return admin, player, card, path, run, target, base


def prompt(admin, base, target, key):
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": target,
            "command_type": "tabletop.dialogue.speak",
            "parameters": {"text": "Hello. How are you?"},
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200, response.get_json()


def provoke(admin, base, target, card, key):
    response = admin.post(
        "/api/v2/commands",
        json={
            **base,
            "embodied_entity_id": target,
            "command_type": "tabletop.combat.attack",
            "parameters": {"target_id": card["entity_id"], "damage_bonus": -10},
            "seed": 2,
            "idempotency_key": key,
        },
    )
    assert response.status_code == 200, response.get_json()


def test_human_reply_volume_and_intent_drive_actual_runner_speech(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    for index in range(4):
        prompt(admin, base, target, f"prompt-{index}")
        response = player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.dialogue.speak",
                "parameters": {"text": "Hello, friend.", "volume": "WHISPER"},
                "idempotency_key": f"reply-{index}",
            },
        )
        assert response.status_code == 200, response.get_json()
    prompt(admin, base, target, "new-prompt")
    profile = player.get(path + "/choice-profile", query_string={"run_id": run}).get_json()
    assert profile["comparable_count"] == 4
    assert "Hello, friend." not in str(profile)
    advice = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "reply-choice"}
    ).get_json()
    assert advice["outcome"]["proposal"]["command_type"] == "tabletop.dialogue.speak"
    assert advice["outcome"]["proposal"]["parameters"]["volume"] == "WHISPER"
    assert (
        "reply"
        not in str(
            player.get(path + "/context", query_string={"run_id": run}).get_json()["situation"]
        ).lower()
    )
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 1,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    assert app.extensions["character_runner"].run_once() == 1
    last = list(app.extensions["simulation"].events.values())[-1]
    assert last.event_type == "tabletop.dialogue.speak" and last.payload["volume"] == "WHISPER"
    evidence = [
        row["choices"]
        for row in app.extensions["simulation"].human_decision_evidence.values()
        if row.get("choices")
    ]
    assert len(evidence) == 4
    # A reply consumes the pending conversational turn; there is no self-response loop.
    after = player.get(path + "/context", query_string={"run_id": run}).get_json()
    assert all(
        row["command_type"] != "tabletop.dialogue.speak" for row in after["action_candidates"]
    )


def test_human_attack_preference_drives_runner_and_uses_only_known_threat(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    before = player.get(path + "/context", query_string={"run_id": run}).get_json()
    assert all(
        row["command_type"] != "tabletop.combat.attack" for row in before["action_candidates"]
    )
    provoke(admin, base, target, card, "provocation")
    for index in range(4):
        response = player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.combat.attack",
                "parameters": {"target_id": target},
                "seed": 2,
                "idempotency_key": f"attack-{index}",
            },
        )
        assert response.status_code == 200, response.get_json()
    advice = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "combat"}
    ).get_json()
    assert advice["choices"]["comparable_count"] == 4
    proposal = advice["outcome"]["proposal"]
    assert (
        proposal["command_type"] == "tabletop.combat.attack"
        and proposal["parameters"]["target_id"] == target
    )
    assert proposal["parameters"]["damage_bonus"] == 0
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 1,
                "idempotency_key": "combat-leave",
            },
        ).status_code
        == 200
    )
    assert app.extensions["character_runner"].run_once() == 1
    assert (
        list(app.extensions["simulation"].events.values())[-1].event_type
        == "tabletop.combat.attack"
    )


def test_unseen_attacker_never_becomes_an_executable_target(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    provoke(admin, base, target, card, "perceived-attack")
    state = app.extensions["simulation"].states.get(uuid.UUID(base["branch_id"]))
    state.projections.setdefault("tabletop.sensory_profiles", {}).setdefault(target, {})[
        "invisible"
    ] = True
    context = player.get(path + "/context", query_string={"run_id": run}).get_json()
    assert all(row["parameters"].get("target_id") != target for row in context["action_candidates"])


def test_demonstrated_retreat_drives_actual_autonomous_movement(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    provoke(admin, base, target, card, "attacked")
    for index in range(4):
        response = player.post(
            "/api/v2/commands",
            json={
                **base,
                "embodied_entity_id": card["entity_id"],
                "command_type": "tabletop.spatial.move",
                "parameters": {"dx": -1, "dy": 0},
                "idempotency_key": f"retreat-{index}",
            },
        )
        assert response.status_code == 200, response.get_json()
    result = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "retreat"}
    ).get_json()
    assert result["outcome"]["proposal"]["parameters"] == {"dx": -1, "dy": 0}
    assert result["choices"]["comparable_count"] > 0
    assert (
        player.post(
            path + "/control",
            json={
                "run_id": run,
                "mode": "AUTONOMOUS",
                "expected_epoch": 0,
                "max_steps": 1,
                "idempotency_key": "leave",
            },
        ).status_code
        == 200
    )
    assert app.extensions["character_runner"].run_once() == 1
    assert list(app.extensions["simulation"].events.values())[-1].payload["destination"]["x"] == -5


def test_pinned_persona_and_card_change_real_combat_decisions_without_history(
    monkeypatch, tmp_path
):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, path, run, target, base = setup_scene(app)
    provoke(admin, base, target, card, "attacked")
    raw = player.get(path + "/context", query_string={"run_id": run}).get_json()
    scene = PerceivedScene.model_validate(player.get(path + "/scene").get_json())
    simulation = app.extensions["simulation"]
    observations = [
        Observation.model_validate(row)
        for row in app.extensions["minds"].inspect(
            uuid.UUID(card["entity_id"]), branch_id=uuid.UUID(base["branch_id"])
        )["observations"]
    ]
    event_order = {event: index for index, event in enumerate(simulation.events)}
    observations.sort(key=lambda row: event_order[row.source_event_id])
    outcomes = []
    for tendency in ("peaceful", "aggressive"):
        content = CharacterCardContent(
            name="Traveler",
            species="Human",
            class_name="Scout",
            background="Traveler",
            level=1,
            ability_scores={},
            authored_identity={"backstory": tendency},
        )
        context = CharacterContext(
            scene=scene,
            observations=tuple(observations),
            beliefs=(),
            memories=(),
            identity=content,
            actions=tuple(DecisionAction.model_validate(row) for row in raw["action_candidates"]),
        )
        persona = CompiledPersona(
            persona_id=uuid.uuid4(),
            persona_version="test",
            compiler_version="test",
            purpose=PersonaPurpose.CHARACTER,
            identity_summary=tendency,
            policy_weights={},
            starting_goals=(),
            retrieval_filters=(),
            deep_traits={
                "risk_tolerance": "LOW" if tendency == "peaceful" else "HIGH",
                "conflict_style": "AVOID" if tendency == "peaceful" else "COMPETE",
            },
        )
        actor = simulation.entities[
            (uuid.UUID(base["branch_id"]), uuid.UUID(card["entity_id"]))
        ].controller_actor_id
        profile = choice_profile(
            context,
            persona,
            run_id=uuid.UUID(run),
            player_actor_id=actor,
            character_id=uuid.UUID(card["character_id"]),
            binding_id=uuid.uuid4(),
            evidence=(),
        )
        result = LayeredDecisionEngine().decide(
            DecisionRequest(
                persona=persona,
                world_id=scene.world_id,
                branch_id=scene.branch_id,
                run_id=uuid.UUID(run),
                actor_id=actor,
                embodied_entity_id=scene.observer_entity_id,
                seed=1,
                idempotency_key="test",
                actions=weighted_choices(context.actions, profile),
                allow_llm=False,
                utility_margin=0,
            )
        )
        outcomes.append(result.proposal.command_type)
    assert outcomes == ["tabletop.dialogue.speak", "tabletop.combat.attack"]

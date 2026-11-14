from __future__ import annotations

import uuid

import pytest

from cognition.behavior import HumanMovementEvidence, behavior_profile, movement_frame
from cognition.context import CharacterContext
from domains.tabletop.character_history import CharacterCardContent
from domains.tabletop.spatial.scene import PerceivedEntity, PerceivedScene, SceneCoordinate
from persona.models import CompiledPersona, PersonaPurpose
from tests.unit.kernel.test_character_binding_api import _app, setup_bound_character

pytestmark = pytest.mark.unit


def movement(card, run, *, key="human", dx=0, dy=-1):
    return dict(
        world_id=card["world_id"],
        branch_id=card["branch_id"],
        run_id=run,
        embodied_entity_id=card["entity_id"],
        command_type="tabletop.spatial.move",
        parameters={"dx": dx, "dy": dy},
        idempotency_key=key,
    )


def test_human_choices_drive_runner_without_learning_its_own_actions(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app)
    card["branch_id"] = str(app.extensions["demo_ids"]["branch_id"])
    for i in range(4):
        body = movement(card, run, key=f"human-{i}")
        result = player.post("/api/v2/commands", json=body)
        assert result.status_code == 200, result.get_json()
        assert player.post("/api/v2/commands", json=body).get_json() == result.get_json()
    simulation = app.extensions["simulation"]
    assert len(simulation.human_decision_evidence) == 4
    profile = player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()
    # One earlier choice had a different perceived distance bucket and is not comparable.
    assert profile["comparable_count"] == 3 and profile["confidence"] == 0.5
    assert "SELF_PRIVATE_MAP" not in str(profile)
    advice = player.post(
        path + "/character-proposals", json={"run_id": run, "idempotency_key": "advice"}
    ).get_json()
    assert advice["outcome"]["proposal"]["parameters"] == {"dx": 0, "dy": -1}
    assert advice["behavior"]["profile_id"] == profile["profile_id"]
    # Taking advice through the human controller is still synthetic preference evidence.
    accepted = player.post(
        "/api/v2/commands", json={**advice["outcome"]["proposal"], "input_origin": "HUMAN_INPUT"}
    )
    assert accepted.status_code == 200
    assert len(simulation.human_decision_evidence) == 4
    handed = player.post(
        path + "/control",
        json={
            "run_id": run,
            "mode": "AUTONOMOUS",
            "expected_epoch": 0,
            "max_steps": 1,
            "idempotency_key": "leave",
        },
    )
    assert handed.status_code == 200
    before = len(simulation.events)
    assert app.extensions["character_runner"].run_once() == 1
    event = list(simulation.events.values())[-1]
    assert len(simulation.events) == before + 1
    assert len(simulation.human_decision_evidence) == 4
    assert event.payload["destination"]["y"] == -6
    assert admin.get(path + "/behavior-profile", query_string={"run_id": run}).status_code == 200
    # The lookback budget belongs to this body, not a busy unrelated world.
    before_other_world = player.get(
        path + "/behavior-profile", query_string={"run_id": run}
    ).get_json()
    original_event = list(simulation.events.values())[-1]
    original_row = next(iter(simulation.human_decision_evidence.values()))
    for _ in range(257):
        foreign_event = uuid.uuid4()
        simulation.events[foreign_event] = original_event.model_copy(
            update={"event_id": foreign_event}
        )
        simulation.human_decision_evidence[foreign_event] = {
            **original_row,
            "world_id": str(uuid.uuid4()),
        }
    assert (
        player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()
        == before_other_world
    )


def test_operator_impersonation_and_failed_move_never_train(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    admin, player, card, _, path, run, _ = setup_bound_character(app)
    card["branch_id"] = str(app.extensions["demo_ids"]["branch_id"])
    body = movement(card, run)
    actor = (
        app.extensions["simulation"]
        .entities[(uuid.UUID(card["branch_id"]), uuid.UUID(card["entity_id"]))]
        .controller_actor_id
    )
    assert (
        admin.post(
            "/api/v2/commands", json={**body, "actor_id": actor, "input_origin": "HUMAN_INPUT"}
        ).status_code
        == 200
    )
    assert not app.extensions["simulation"].human_decision_evidence
    failed = player.post(
        "/api/v2/commands",
        json={**body, "idempotency_key": "invalid", "parameters": {"dx": 99, "dy": 0}},
    )
    assert failed.status_code == 400
    assert not app.extensions["simulation"].human_decision_evidence
    assert (
        player.get(
            path + "/behavior-profile", query_string={"run_id": str(uuid.uuid4())}
        ).status_code
        == 400
    )


@pytest.mark.parametrize("source", ["persona", "backstory"])
def test_history_free_caution_and_curiosity_change_real_action_scores(source):
    world, branch, body, other, run, player, char, binding = [uuid.uuid4() for _ in range(8)]
    scene = PerceivedScene(
        world_id=world,
        branch_id=branch,
        observer_entity_id=body,
        projection_version=1,
        visible_zones=("world",),
        recent_observations=(),
        available_viewpoints=(body,),
        perceived_entities=(
            PerceivedEntity(
                entity_id=body,
                position=SceneCoordinate(x=0, y=0),
                position_confidence=1,
                knowledge_state="VISIBLE",
                detail_level="INSPECTED",
            ),
            PerceivedEntity(
                entity_id=other,
                position=SceneCoordinate(x=3, y=0),
                position_confidence=1,
                knowledge_state="VISIBLE",
                detail_level="IDENTIFIED",
            ),
        ),
    )
    results = []
    for tendency in ("cautious", "curious"):
        identity = CharacterCardContent(
            name="Traveler",
            species="Human",
            class_name="Scout",
            background="Wanderer",
            level=1,
            ability_scores={},
            authored_identity={"backstory": tendency if source == "backstory" else ""},
        )
        context = CharacterContext(
            scene=scene, identity=identity, observations=(), beliefs=(), memories=()
        )
        persona = CompiledPersona(
            persona_id=char,
            persona_version="1",
            compiler_version="test",
            purpose=PersonaPurpose.CHARACTER,
            identity_summary="Traveler",
            starting_goals=(),
            retrieval_filters=(),
            policy_weights={
                "curiosity": 0.25 if tendency == "cautious" else 0.85,
                "risk_penalty": 1.55 if tendency == "cautious" else 0.95,
            }
            if source == "persona"
            else {},
        )
        profile = behavior_profile(
            context,
            persona,
            character_id=char,
            binding_id=binding,
            run_id=run,
            player_actor_id=player,
            evidence=(),
        )
        results.append(profile.direction_scores)
        if tendency == "cautious":
            sample = HumanMovementEvidence(
                world_id=world,
                branch_id=branch,
                run_id=run,
                entity_id=body,
                player_actor_id=player,
                character_id=char,
                binding_id=binding,
                projection_version=1,
                frame=movement_frame(scene),
                chosen="east",
            )
            demonstrated = behavior_profile(
                context,
                persona,
                character_id=char,
                binding_id=binding,
                run_id=run,
                player_actor_id=player,
                evidence=tuple((uuid.uuid4(), sample) for _ in range(4)),
            )
            assert demonstrated.direction_scores["east"] > demonstrated.direction_scores["west"]
            if source == "backstory":
                assert demonstrated.conflicts
    assert results[0]["west"] > results[0]["east"]
    assert results[1]["east"] > results[1]["west"]


@pytest.mark.parametrize(
    "field", ["branch_id", "run_id", "character_id", "player_actor_id", "entity_id"]
)
def test_other_timeline_player_character_evidence_is_excluded(field, monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    _, player, card, _, path, run, _ = setup_bound_character(app)
    card["branch_id"] = str(app.extensions["demo_ids"]["branch_id"])
    for index in range(3):
        assert (
            player.post("/api/v2/commands", json=movement(card, run, key=str(index))).status_code
            == 200
        )
    assert (
        player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()[
            "comparable_count"
        ]
        > 0
    )
    for row in app.extensions["simulation"].human_decision_evidence.values():
        row[field] = str(uuid.uuid4())
    assert (
        player.get(path + "/behavior-profile", query_string={"run_id": run}).get_json()[
            "comparable_count"
        ]
        == 0
    )

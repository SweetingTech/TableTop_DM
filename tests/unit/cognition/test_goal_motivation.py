from __future__ import annotations

import uuid

import pytest

from cognition.context import build_character_context
from cognition.goal_motivation import derive_motivation
from cognition.models import Observation
from domains.tabletop.spatial.scene import PerceivedScene
from persona.models import CompiledPersona, PersonaPurpose
from tests.unit.kernel.test_character_binding_api import _app
from tests.unit.kernel.test_npc_goals import configure_subjective, say

pytestmark = pytest.mark.unit


def frame(app, data):
    game, card, path, association, config = data
    admin, player, player_card, player_path, run, target, base = game
    sim = app.extensions["simulation"]
    branch, entity = uuid.UUID(base["branch_id"]), uuid.UUID(target)
    actor = app.extensions["demo_ids"]["actor_id"]
    binding = app.extensions["character_bindings"].latest(
        (uuid.UUID(base["world_id"]), branch, uuid.UUID(run), entity), actor_id=actor
    )
    profile = CompiledPersona.model_validate(
        admin.post(f"/api/v2/personas/{binding.persona_id}/compile").get_json()
    )
    store = app.extensions["minds"]
    context = build_character_context(
        scene=PerceivedScene.model_validate(admin.get(path + "/scene").get_json()),
        mind=store.get(entity, branch_id=branch),
        observations=tuple(
            Observation.model_validate(row)
            for row in store.inspect(entity, branch_id=branch)["observations"]
        ),
        actor_id=actor,
        event_reader=sim.events.get,
        grant_reader=lambda event, body: sim.perceptions.get((event, body)),
    )
    from population.routines import RoutineRequest

    life = RoutineRequest.model_validate(config).model_dump(mode="json")["life"]
    return context, binding, profile, life["planning"]["goals"], life["home"]


def test_policy_rejects_playtester_or_foreign_body_context(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    args = frame(app, configure_subjective(app))
    context, binding, profile, goals, home = args
    with pytest.raises(ValueError, match="CHARACTER"):
        derive_motivation(
            context,
            binding,
            profile.model_copy(update={"purpose": PersonaPurpose.SIMULATED_PLAYTESTER}),
            goals,
            home,
            1,
        )
    with pytest.raises(ValueError, match="binding"):
        derive_motivation(
            context, binding.model_copy(update={"entity_id": uuid.uuid4()}), profile, goals, home, 1
        )


def test_operational_scene_versions_do_not_change_semantic_input_hash(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    context, binding, profile, goals, home = frame(app, configure_subjective(app))
    one = derive_motivation(context, binding, profile, goals, home, 1)
    two = derive_motivation(
        context.model_copy(
            update={"scene": context.scene.model_copy(update={"projection_version": 999})}
        ),
        binding,
        profile,
        goals,
        home,
        1,
    )
    assert one == two


def test_danger_respects_risk_tolerance_and_frozen_source_confidence(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    data = configure_subjective(app)
    admin, player, card, path, run, target, base = data[0]
    say(
        player,
        base,
        card,
        "place_danger",
        {"place": {"x": 1, "y": 0}, "dangerous": True},
        subject_type="place",
    )
    context, binding, profile, goals, home = frame(app, data)
    narrowed = context.model_copy(
        update={
            "observations": tuple(
                row.model_copy(update={"confidence": 0.4}) for row in context.observations
            )
        }
    )
    assert derive_motivation(narrowed, binding, profile, goals, home, 1).avoided
    bold = profile.model_copy(
        update={"deep_traits": {**profile.deep_traits, "risk_tolerance": "HIGH"}}
    )
    assert not derive_motivation(narrowed, binding, bold, goals, home, 1).avoided


def test_forged_value_or_superseded_belief_cannot_supply_goal_influence(monkeypatch, tmp_path):
    app = _app(monkeypatch, tmp_path)
    data = configure_subjective(app)
    admin, player, card, path, run, target, base = data[0]
    say(
        player,
        base,
        card,
        "motive_importance",
        {"motive": "CURIOSITY", "importance": 50},
        subject_id=target,
    )
    context, binding, profile, goals, home = frame(app, data)
    belief = next(row for row in context.beliefs if row.predicate == "motive_importance")
    baseline = derive_motivation(
        context.model_copy(update={"beliefs": ()}), binding, profile, goals, home, 1
    )
    for changed in (
        belief.model_copy(update={"value": {"motive": "CURIOSITY", "importance": 100}}),
        belief.model_copy(update={"contradicted_by_event_id": uuid.uuid4()}),
    ):
        result = derive_motivation(
            context.model_copy(update={"beliefs": (changed,)}), binding, profile, goals, home, 1
        )
        assert result.priorities == baseline.priorities and not result.belief_ids

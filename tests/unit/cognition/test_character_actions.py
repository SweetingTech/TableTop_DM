from __future__ import annotations

import json
import uuid

import pytest

from cognition.context import CharacterContext
from domains.tabletop.character_actions import character_action_candidates
from domains.tabletop.parties import InvitationView
from domains.tabletop.spatial import MoveRequest
from domains.tabletop.spatial.scene import PerceivedEntity, PerceivedScene, SceneCoordinate
from kernel.contracts import Actor, ActorKind, BranchKind
from persona.models import CompiledPersona, PersonaPurpose

pytestmark = pytest.mark.unit


def _fixture():
    entity = uuid.uuid4()
    scene = PerceivedScene(
        observer_entity_id=entity,
        world_id=uuid.uuid4(),
        branch_id=uuid.uuid4(),
        projection_version=7,
        visible_zones=("garden",),
        available_viewpoints=(entity,),
        perceived_entities=(
            PerceivedEntity(
                entity_id=entity,
                name="Gardener",
                position=SceneCoordinate(x=2, y=3),
                position_confidence=1,
                knowledge_state="VISIBLE",
                detail_level="INSPECTED",
                health=10,
                status="ACTIVE",
            ),
        ),
        recent_observations=(),
    )
    actor = Actor(
        actor_id=uuid.uuid4(),
        display_name="Scene controller",
        kind=ActorKind.HUMAN,
        capabilities=frozenset({"action.propose", "entity.act", "action.commit"}),
        controlled_entity_ids=frozenset({entity}),
    )
    return scene, actor


def test_catalog_is_deterministic_typed_and_contains_only_in_world_action_labels():
    scene, actor = _fixture()
    before = scene.model_dump_json()
    choices = character_action_candidates(scene, actor=actor, branch_kind=BranchKind.CANONICAL)
    assert len(choices) == 4
    assert len({c.action for c in choices}) == 4
    for choice in choices:
        assert choice.command_type == "tabletop.spatial.move"
        assert MoveRequest.model_validate(choice.parameters)
        assert "Try to take one step" in choice.action
    assert choices == character_action_candidates(
        scene, actor=actor, branch_kind=BranchKind.CANONICAL
    )
    assert scene.model_dump_json() == before
    serialized = json.dumps([c.model_dump(mode="json") for c in choices])
    for identity in [scene.world_id, scene.branch_id, scene.observer_entity_id, actor.actor_id]:
        assert str(identity) not in serialized


@pytest.mark.parametrize("capability", ["action.propose", "entity.act", "action.commit"])
def test_missing_world_capability_never_yields_executable_choices(capability):
    scene, actor = _fixture()
    actor = actor.model_copy(update={"capabilities": actor.capabilities - {capability}})
    assert character_action_candidates(scene, actor=actor, branch_kind=BranchKind.CANONICAL) == ()


def test_inspection_authority_is_not_control_and_trials_do_not_require_commit():
    scene, actor = _fixture()
    inspector = actor.model_copy(
        update={
            "controlled_entity_ids": frozenset(),
            "capabilities": actor.capabilities | {"world.read.all", "mind.read.all"},
        }
    )
    assert (
        character_action_candidates(scene, actor=inspector, branch_kind=BranchKind.CANONICAL) == ()
    )
    trial_actor = actor.model_copy(update={"capabilities": actor.capabilities - {"action.commit"}})
    assert (
        len(character_action_candidates(scene, actor=trial_actor, branch_kind=BranchKind.TRIAL))
        == 4
    )


@pytest.mark.parametrize(
    "changes", [{"position": None}, {"health": 0}, {"status": "DEAD"}, {"status": "UNCONSCIOUS"}]
)
def test_missing_body_or_observed_incapacity_yields_no_movement(changes):
    scene, actor = _fixture()
    body = scene.perceived_entities[0].model_copy(update=changes)
    assert (
        character_action_candidates(
            scene.model_copy(update={"perceived_entities": (body,)}),
            actor=actor,
            branch_kind=BranchKind.CANONICAL,
        )
        == ()
    )
    assert (
        character_action_candidates(
            scene.model_copy(update={"perceived_entities": ()}),
            actor=actor,
            branch_kind=BranchKind.CANONICAL,
        )
        == ()
    )


def test_other_entities_do_not_change_or_add_targets_to_basic_movement_choices():
    scene, actor = _fixture()
    expected = character_action_candidates(scene, actor=actor, branch_kind=BranchKind.CANONICAL)
    stranger = scene.perceived_entities[0].model_copy(
        update={
            "entity_id": uuid.uuid4(),
            "name": "Secret plot NPC",
            "position": SceneCoordinate(x=99, y=100),
        }
    )
    expanded = scene.model_copy(
        update={"perceived_entities": (*scene.perceived_entities, stranger)}
    )
    assert (
        character_action_candidates(expanded, actor=actor, branch_kind=BranchKind.CANONICAL)
        == expected
    )


def test_unreachable_invites_do_not_displace_the_nearby_party_offer():
    scene, actor = _fixture()
    self_view = scene.perceived_entities[0]
    absent = self_view.model_copy(update={"entity_id": uuid.uuid4()})
    distant = self_view.model_copy(
        update={"entity_id": uuid.uuid4(), "position": SceneCoordinate(x=10, y=3)}
    )
    nearby = self_view.model_copy(
        update={"entity_id": uuid.uuid4(), "position": SceneCoordinate(x=3, y=3)}
    )

    def invite(inviter, name):
        return InvitationView(
            party_id=uuid.uuid4(),
            invitation_id=uuid.uuid4(),
            inviter_id=inviter.entity_id,
            invitee_id=self_view.entity_id,
            name=name,
            goal="Carry water to the garden.",
        )

    live = invite(nearby, "Neighbors at the gate")
    scene = scene.model_copy(
        update={
            "perceived_entities": (self_view, distant, nearby),
            "party_invitations": (
                *tuple(invite(absent, "Absent") for _ in range(4)),
                *tuple(invite(distant, "Distant") for _ in range(4)),
                live,
            ),
        }
    )
    persona = CompiledPersona(
        persona_id=uuid.uuid4(),
        purpose=PersonaPurpose.CHARACTER,
        persona_version="fixed",
        compiler_version="fixed",
        identity_summary="A gardener",
        policy_weights={},
        starting_goals=(),
        retrieval_filters=(),
    )
    candidates = character_action_candidates(
        scene, actor=actor, branch_kind=BranchKind.CANONICAL, persona=persona
    )
    responses = [row for row in candidates if row.command_type == "tabletop.party.respond"]
    assert {row.action for row in responses} == {
        "Accept party invitation 1",
        "Decline party invitation 1",
    }
    assert {row.parameters["invitation_id"] for row in responses} == {str(live.invitation_id)}
    situation = CharacterContext(
        scene=scene, observations=(), beliefs=(), memories=(), actions=candidates
    ).situation()
    assert [(row["reference"], row["name"]) for row in situation["party_invitations"]] == [
        ("party invitation 1", live.name),
    ]

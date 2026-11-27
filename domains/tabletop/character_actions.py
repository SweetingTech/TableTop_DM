"""Basic in-world attempts, without consulting hidden truth to rank or filter choices."""

from __future__ import annotations

from cognition.choice_state import SPEECH, VOLUMES, ChoiceFrame, choice_frame
from cognition.engine import DecisionAction
from cognition.goal_motivation import LEVEL, MOTIVE_TRAITS
from cognition.models import Observation
from domains.tabletop.combat import AttackRequest
from domains.tabletop.combat import command_definition as attack_definition
from domains.tabletop.dialogue import SpeechRequest
from domains.tabletop.magic.tactical import InvokeRequest
from domains.tabletop.parties import RespondToInvitation
from domains.tabletop.party_coordination import FollowPlan
from domains.tabletop.rules import DEFAULT_SPELLS
from domains.tabletop.spatial import MoveRequest, command_definition
from domains.tabletop.spatial.scene import PerceivedScene, SceneCoordinate
from kernel.contracts import Actor, BranchKind
from persona.models import CompiledPersona

ACTION_CATALOG_VERSION = "tabletop-character-actions-1.7.0"
_DIRECTIONS = (("north", 0, -1), ("east", 1, 0), ("south", 0, 1), ("west", -1, 0))


def _motive_weight(persona: CompiledPersona, motive: str) -> float:
    # A strong motive can compete with an established movement preference.
    return (
        sum(LEVEL.get(str(persona.deep_traits.get(trait)), 0) for trait in MOTIVE_TRAITS[motive])
        / 32
    )


def _invitation_actions(
    scene: PerceivedScene, origin: SceneCoordinate, persona: CompiledPersona, frame: ChoiceFrame
) -> tuple[DecisionAction, ...]:
    visible = {
        entity.entity_id: entity
        for entity in scene.perceived_entities
        if entity.knowledge_state == "VISIBLE"
    }
    threats = {threat.entity_id for threat in frame.threats}
    actions: list[DecisionAction] = []
    for index, invitation in enumerate(scene.party_invitations[:8], 1):
        inviter = visible.get(invitation.inviter_id)
        location = inviter.position if inviter and inviter.status in {None, "ACTIVE"} else None
        if (
            location is None
            or (location.zone_id, location.z) != (origin.zone_id, origin.z)
            or max(abs(location.x - origin.x), abs(location.y - origin.y)) > 1
        ):
            continue
        temperament = _motive_weight(persona, invitation.motive)
        hostilities = -1.5 if invitation.inviter_id in threats else 0.0
        for accept, response, direction in ((True, "Accept", 1), (False, "Decline", -1)):
            actions.append(
                DecisionAction(
                    action=f"{response} party invitation {index}",
                    command_type="tabletop.party.respond",
                    parameters=RespondToInvitation(
                        invitation_id=invitation.invitation_id, accept=accept
                    ).model_dump(mode="json"),
                    utility_factors={
                        "offered_motive": direction * temperament,
                        "witnessed_hostility": direction * hostilities,
                    },
                )
            )
    return tuple(actions)


def _party_travel_options(
    scene: PerceivedScene, origin: SceneCoordinate, persona: CompiledPersona
) -> tuple[dict[str, float], tuple[DecisionAction, ...]]:
    move_weights: dict[str, float] = {}
    choices: list[DecisionAction] = []
    for index, party in enumerate(scene.parties, 1):
        waypoint = party.waypoint
        if (
            waypoint is None
            or party.plan_event_id is None
            or (waypoint.zone_id, waypoint.z) != (str(origin.zone_id), origin.z)
            or (waypoint.x, waypoint.y) == (origin.x, origin.y)
        ):
            continue
        if scene.observer_entity_id not in party.following_member_ids:
            choices.append(
                DecisionAction(
                    action=f"Agree to follow party plan {index}",
                    command_type="tabletop.party.follow",
                    parameters=FollowPlan(
                        party_id=party.party_id,
                        plan_event_id=party.plan_event_id,
                        follow=True,
                    ).model_dump(mode="json"),
                    utility_factors={"agreed_goal": _motive_weight(persona, party.motive)},
                )
            )
            continue
        distance = abs(waypoint.x - origin.x) + abs(waypoint.y - origin.y)
        move_weights.update(
            {
                name: 1.5
                for name, dx, dy in _DIRECTIONS
                if abs(waypoint.x - origin.x - dx) + abs(waypoint.y - origin.y - dy) < distance
            }
        )
        break
    return move_weights, tuple(choices)


def character_action_candidates(
    scene: PerceivedScene,
    *,
    actor: Actor,
    branch_kind: BranchKind,
    observations: tuple[Observation, ...] = (),
    persona: CompiledPersona | None = None,
) -> tuple[DecisionAction, ...]:
    """Caller supplies world-scoped authority, after authorizing this exact scene.

    These are permitted attempts, not promises of success. Hidden obstacles/resources must
    never become an oracle through a missing choice. The kernel revalidates every proposal.
    No account role, protagonist status, class, or species decides who can move.
    """
    definition = command_definition()
    needed = definition.required_capabilities | {
        "action.commit" if branch_kind is BranchKind.CANONICAL else "action.propose"
    }
    if (
        branch_kind not in definition.allowed_branch_kinds
        or not actor.has_capabilities(needed)
        or scene.observer_entity_id not in actor.controlled_entity_ids
    ):
        return ()
    body = next(
        (item for item in scene.perceived_entities if item.entity_id == scene.observer_entity_id),
        None,
    )
    if (
        body is None
        or body.position is None
        or (body.health is not None and body.health <= 0)
        or body.status in {"DEAD", "DEFEATED", "UNCONSCIOUS", "INCAPACITATED"}
        or bool(body.action_wait_seconds)
    ):
        return ()
    frame = choice_frame(scene, observations)
    move_weights, party_choices = (
        _party_travel_options(scene, body.position, persona)
        if frame is not None and not frame.threats and persona is not None
        else ({}, ())
    )
    actions = (
        tuple(
            DecisionAction(
                action=f"Try to take one step {name}",
                command_type=definition.command_type,
                parameters=MoveRequest(dx=dx, dy=dy).model_dump(mode="json"),
                utility_factors={"party_waypoint": move_weights[name]}
                if name in move_weights
                else {},
            )
            for name, dx, dy in _DIRECTIONS
        )
        + party_choices
    )
    if frame is not None and persona is not None:
        actions += _invitation_actions(scene, body.position, persona, frame)
    if frame is not None and frame.speech_ready:
        actions += tuple(
            DecisionAction(
                action=f"Say {intent.lower()} in a {volume.lower()} voice",
                command_type="tabletop.dialogue.speak",
                parameters=SpeechRequest(text=text, volume=volume).model_dump(mode="json"),
            )
            for intent, text in SPEECH.items()
            for volume in VOLUMES
        )
    if frame is not None and actor.has_capabilities(attack_definition().required_capabilities):
        actions += tuple(
            DecisionAction(
                action=f"Try a basic melee attack against perceived threat {index + 1}",
                command_type="tabletop.combat.attack",
                parameters=AttackRequest(target_id=threat.entity_id).model_dump(mode="json"),
            )
            for index, threat in enumerate(frame.threats)
            if body.attack_reach != 0 and threat.distance <= (body.attack_reach or 1)
        )
    if frame is not None and frame.threats:
        if not frame.guarded:
            actions += (
                DecisionAction(
                    action="Take a defensive guard",
                    command_type="tabletop.combat.guard",
                    parameters={},
                ),
            )
        spells = body.known_spell_ids if body.known_spell_ids is not None else DEFAULT_SPELLS
        if frame.mana >= 2:
            actions += tuple(
                DecisionAction(
                    action=f"Try an arcane bolt at perceived threat {index + 1}",
                    command_type="tabletop.magic.invoke",
                    parameters=InvokeRequest(
                        spell_id="ARCANE_BOLT", target_id=threat.entity_id
                    ).model_dump(mode="json"),
                )
                for index, threat in enumerate(frame.threats)
                if threat.distance <= 6 and "ARCANE_BOLT" in spells
            )
    if frame is not None and (frame.threats or frame.support_targets):
        spells = body.known_spell_ids if body.known_spell_ids is not None else DEFAULT_SPELLS
        if (
            frame.mana >= 2
            and "MEND" in spells
            and body.health is not None
            and body.max_health
            and body.health < body.max_health
        ):
            actions += (
                DecisionAction(
                    action="Try to mend my wounds",
                    command_type="tabletop.magic.invoke",
                    parameters=InvokeRequest(spell_id="MEND", target_id=body.entity_id).model_dump(
                        mode="json"
                    ),
                ),
            )
        actions += tuple(
            DecisionAction(
                action=f"Try to mend the wounds of past helper {index + 1}",
                command_type="tabletop.magic.invoke",
                parameters=InvokeRequest(spell_id="MEND", target_id=target).model_dump(mode="json"),
            )
            for index, target in enumerate(frame.support_targets)
        )
    return actions

"""Basic in-world attempts, without consulting hidden truth to rank or filter choices."""

from __future__ import annotations

from cognition.choice_state import SPEECH, VOLUMES, choice_frame
from cognition.engine import DecisionAction
from cognition.models import Observation
from domains.tabletop.combat import AttackRequest
from domains.tabletop.combat import command_definition as attack_definition
from domains.tabletop.dialogue import SpeechRequest
from domains.tabletop.spatial import MoveRequest, command_definition
from domains.tabletop.spatial.scene import PerceivedScene
from kernel.contracts import Actor, BranchKind

ACTION_CATALOG_VERSION = "tabletop-character-actions-1.1.0"
_DIRECTIONS = (("north", 0, -1), ("east", 1, 0), ("south", 0, 1), ("west", -1, 0))


def character_action_candidates(
    scene: PerceivedScene,
    *,
    actor: Actor,
    branch_kind: BranchKind,
    observations: tuple[Observation, ...] = (),
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
    ):
        return ()
    actions = tuple(
        DecisionAction(
            action=f"Try to take one step {name}",
            command_type=definition.command_type,
            parameters=MoveRequest(dx=dx, dy=dy).model_dump(mode="json"),
        )
        for name, dx, dy in _DIRECTIONS
    )
    frame = choice_frame(scene, observations)
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
            if threat.distance <= 1
        )
    return actions

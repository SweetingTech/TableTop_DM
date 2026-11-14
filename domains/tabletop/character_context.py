"""Trusted composition shared by character-context reads and proposal generation."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from cognition.context import CharacterContext, build_character_context
from cognition.models import Observation
from cognition.store import MindStore
from domains.tabletop.character_actions import character_action_candidates
from domains.tabletop.character_bindings import CharacterBinding, CharacterBindingRepository
from domains.tabletop.portal import PortalRepository
from domains.tabletop.spatial.scene import PerceivedScene
from kernel.application import SimulationApplication
from kernel.contracts import RunKind
from persona.models import CompiledPersona, PersonaPurpose

ProfileReader = Callable[[uuid.UUID, uuid.UUID, str], CompiledPersona | None]


@dataclass(frozen=True)
class ResolvedCharacterContext:
    context: CharacterContext
    binding: CharacterBinding | None
    profile: CompiledPersona | None


def resolve_character_context(
    *,
    simulation: SimulationApplication,
    scene: PerceivedScene,
    minds: MindStore,
    actor_id: uuid.UUID,
    run_id: uuid.UUID | None,
    bindings: CharacterBindingRepository,
    cards: PortalRepository,
    profile_reader: ProfileReader,
) -> ResolvedCharacterContext:
    world, branch, entity = scene.world_id, scene.branch_id, scene.observer_entity_id
    if run_id is not None:
        run = simulation.runs.get(run_id)
        if run is None or (run.world_id, run.branch_id) != (world, branch):
            raise ValueError("context run does not belong to this world and branch")
    else:
        runs = [
            row
            for row in simulation.runs.values()
            if (row.world_id, row.branch_id) == (world, branch)
            and row.kind is RunKind.LIVE
            and row.status in {"ACTIVE", "RUNNING", "PAUSED", "QUEUED"}
        ]
        if len(runs) > 1:
            raise ValueError("multiple live runs; select run_id for character context")
        run = runs[0] if runs else None
    authority = simulation.authority(world, actor_id)
    can_read = (
        entity in authority.controlled_entity_ids or "mind.read.all" in authority.capabilities
    )
    binding = (
        bindings.latest((world, branch, run.run_id, entity), actor_id=actor_id)
        if run and can_read
        else None
    )
    profile = None
    identity = None
    if binding:
        revision = next(
            (
                row
                for row in cards.character_revisions(binding.character_id, actor_id=actor_id)
                if row.revision_id == binding.card_revision_id
            ),
            None,
        )
        profile = profile_reader(
            binding.persona_id, binding.persona_version_id, binding.compiler_version
        )
        if (
            revision is None
            or profile is None
            or profile.purpose is not PersonaPurpose.CHARACTER
            or (profile.persona_id, profile.persona_version, profile.compiler_version)
            != (binding.persona_id, str(binding.persona_version_id), binding.compiler_version)
        ):
            raise ValueError("pinned character identity is unavailable")
        identity = revision.content
    context = build_character_context(
        identity=identity,
        scene=scene,
        mind=minds.get(entity, branch_id=branch),
        actor_id=actor_id,
        observations=tuple(
            Observation.model_validate(row)
            for row in minds.inspect(entity, branch_id=branch)["observations"]
        ),
        event_reader=simulation.events.get,
        grant_reader=lambda event, observer: simulation.perceptions.get((event, observer)),
        action_provider=lambda authorized_scene: character_action_candidates(
            authorized_scene, actor=authority, branch_kind=simulation.states.get(branch).kind
        ),
    )
    return ResolvedCharacterContext(context, binding, profile)

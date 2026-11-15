"""Trusted composition for observation-grounded offscreen NPC intentions."""

from __future__ import annotations

import copy
import uuid
from collections.abc import Callable

from flask import Flask, jsonify, request
from pydantic import BaseModel, ConfigDict

from cognition.character_decisions import (
    CharacterProposalScope,
    require_projected_character_experience,
)
from cognition.context import build_character_context
from cognition.goal_motivation import derive_motivation
from cognition.models import Observation
from cognition.store import MindStore
from domains.tabletop.character_bindings import CharacterBindingRepository
from domains.tabletop.character_context import ProfileReader
from domains.tabletop.portal import TabletopPortalService
from domains.tabletop.spatial.service import build_perceived_scene
from identity.models import UserAccount
from identity.service import IdentityService
from kernel.application import SimulationApplication
from kernel.contracts import BranchKind
from kernel.control import ControlScope
from kernel.state import InMemoryStateStore
from population.motivation import GoalInputReader


def make_goal_reader(
    snapshot: Callable[[], SimulationApplication],
    read_minds: Callable[[ControlScope, uuid.UUID], MindStore],
    bindings: CharacterBindingRepository,
    profiles: ProfileReader,
) -> GoalInputReader:
    def read(proposal, before):
        source = copy.copy(snapshot())
        source.states = InMemoryStateStore()
        source.states.add(before.working_copy())
        authority = source.authority(proposal.world_id, proposal.actor_id)
        result = {}
        for key, row in sorted(before.projections.get("tabletop.routines", {}).items()):
            planning = (row.get("life") or {}).get("planning")
            if not row["enabled"] or not planning or not planning.get("motivated"):
                continue
            entity = uuid.UUID(key)
            if "mind.read.all" not in authority.capabilities and not (
                entity in authority.controlled_entity_ids and "entity.act" in authority.capabilities
            ):
                raise PermissionError("NPC goal planning requires world-scoped mind access")
            scope = CharacterProposalScope(
                world_id=proposal.world_id,
                branch_id=proposal.branch_id,
                run_id=proposal.run_id,
                entity_id=entity,
            )
            minds = read_minds(ControlScope(**scope.model_dump()), proposal.actor_id)
            require_projected_character_experience(source, minds, scope, proposal.actor_id)
            scene = build_perceived_scene(
                source,
                minds,
                world_id=proposal.world_id,
                branch_id=proposal.branch_id,
                observer_entity_id=entity,
                actor_id=proposal.actor_id,
            )
            binding = bindings.latest(scope.key, actor_id=proposal.actor_id)
            profile = (
                profiles(binding.persona_id, binding.persona_version_id, binding.compiler_version)
                if binding
                else None
            )
            if binding is None or profile is None:
                raise ValueError("NPC goal planning requires an existing pinned CHARACTER binding")
            context = build_character_context(
                scene=scene,
                mind=minds.get(entity, branch_id=proposal.branch_id),
                observations=tuple(
                    Observation.model_validate(row)
                    for row in minds.inspect(entity, branch_id=proposal.branch_id)["observations"]
                ),
                actor_id=proposal.actor_id,
                event_reader=source.events.get,
                grant_reader=lambda event, observer: source.perceptions.get((event, observer)),
                event_order={event: index for index, event in enumerate(source.events)},
            )
            result[key] = derive_motivation(
                context,
                binding,
                profile,
                planning["goals"],
                row["life"]["home"],
                source.runs[proposal.run_id].seed,
            )
        return result

    return read


class NpcCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: uuid.UUID


def register_npc_card_binding(
    app: Flask,
    snapshot: Callable[[], SimulationApplication],
    user: Callable[[], UserAccount],
    actor: Callable[[], uuid.UUID],
    require_world: Callable[[uuid.UUID], None],
    portal: TabletopPortalService,
) -> None:
    @app.put(
        "/api/v2/dm/worlds/<uuid:world_id>/branches/<uuid:branch_id>/entities/<uuid:entity_id>/character-card"
    )
    def associate(world_id: uuid.UUID, branch_id: uuid.UUID, entity_id: uuid.UUID):
        account = user()
        IdentityService.require_world_role(account, world_id, "DM")
        require_world(world_id)
        source = snapshot()
        authority = source.authority(world_id, actor())
        if not {"entity.control", "mind.write.all"} <= authority.capabilities:
            raise PermissionError("NPC card association requires world character management")
        branch = source.states.get(branch_id)
        body = source.entities.get((branch_id, entity_id))
        if (
            branch.world_id != world_id
            or branch.kind is not BranchKind.CANONICAL
            or body is None
            or body.world_id != world_id
        ):
            raise ValueError("NPC card association requires a canonical body in this world")
        payload = NpcCardRequest.model_validate(request.get_json(force=True))
        character = portal.repository.get_character(payload.character_id)
        if character is None:
            raise KeyError(payload.character_id)
        if any(
            row.entity_id == entity_id
            and row.world_id == world_id
            and row.character_id != character.character_id
            for row in portal.repository.list_characters()
        ):
            raise ValueError("body already represents another character card")
        if (character.world_id, character.entity_id) == (world_id, entity_id):
            return jsonify({"character": character.model_dump(mode="json")})
        saved = portal.bind_character_entity(
            account, character.character_id, world_id=world_id, entity_id=entity_id
        )
        persisted = portal.repository.get_character(saved.character_id) or saved
        return jsonify({"character": persisted.model_dump(mode="json")})

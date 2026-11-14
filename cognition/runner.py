"""Bounded unattended decisions through the normal authorized kernel command path."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable

from cognition.character_decisions import (
    CharacterContextPending,
    CharacterProposalReceipt,
    CharacterProposalRepository,
    CharacterProposalScope,
    propose_for_character,
    require_character_proposal_authority,
    require_projected_character_experience,
)
from cognition.control import ControllerRepository
from cognition.store import MindStore
from domains.tabletop.character_bindings import CharacterBindingRepository
from domains.tabletop.character_context import ProfileReader, resolve_character_context
from domains.tabletop.portal import PortalRepository
from domains.tabletop.spatial.service import build_perceived_scene
from kernel.application import SimulationApplication
from kernel.control import ControllerState, ControlScope
from kernel.errors import KernelError


class CharacterDecisionService:
    def __init__(
        self,
        *,
        snapshot: Callable[[], SimulationApplication],
        read_minds: Callable[[ControlScope, uuid.UUID], MindStore],
        bindings: CharacterBindingRepository,
        cards: PortalRepository,
        profiles: ProfileReader,
        proposals: CharacterProposalRepository,
        reference: SimulationApplication | None,
    ) -> None:
        self.snapshot, self.read_minds = snapshot, read_minds
        self.bindings, self.cards, self.profiles = bindings, cards, profiles
        self.proposals, self.reference = proposals, reference

    def decide(
        self,
        scope: ControlScope,
        actor_id: uuid.UUID,
        key: str,
        controller: ControllerState | None = None,
    ) -> CharacterProposalReceipt:
        proposal_scope = CharacterProposalScope.model_validate(scope.model_dump())

        def generate():
            source = self.snapshot()
            require_character_proposal_authority(source, proposal_scope, actor_id)
            if source.runs[scope.run_id].status not in {"ACTIVE", "RUNNING"}:
                raise ValueError("character proposals require an active run")
            minds = self.read_minds(scope, actor_id)
            scene = build_perceived_scene(
                source,
                minds,
                world_id=scope.world_id,
                branch_id=scope.branch_id,
                observer_entity_id=scope.entity_id,
                actor_id=actor_id,
            )
            require_projected_character_experience(source, minds, proposal_scope, actor_id)
            resolved = resolve_character_context(
                simulation=source,
                scene=scene,
                minds=minds,
                actor_id=actor_id,
                run_id=scope.run_id,
                bindings=self.bindings,
                cards=self.cards,
                profile_reader=self.profiles,
            )
            if resolved.binding is None or resolved.profile is None:
                raise ValueError("a pinned character binding is required")
            return propose_for_character(
                scope=proposal_scope,
                actor_id=actor_id,
                key=key,
                run_seed=source.runs[scope.run_id].seed,
                context=resolved.context,
                binding=resolved.binding,
                profile=resolved.profile,
                controller=controller,
                human_epoch=source.controller_states[scope.key].epoch
                if scope.key in source.controller_states
                else None,
            )

        def create():
            if self.reference is not None:
                require_character_proposal_authority(self.reference, proposal_scope, actor_id)
            return self.proposals.get_or_create(proposal_scope, actor_id, key, generate)

        return self.reference.read_reference(create) if self.reference else create()


class CharacterRunner:
    def __init__(
        self,
        controllers: ControllerRepository,
        decisions: CharacterDecisionService,
        snapshot: Callable[[], SimulationApplication],
    ) -> None:
        self.controllers, self.decisions, self.snapshot = controllers, decisions, snapshot

    def run_once(self) -> int:
        committed = 0
        for controller in self.controllers.due():
            try:
                receipt = self.decisions.decide(
                    controller.scope,
                    controller.executor_actor_id,
                    f"controller:{controller.epoch}:step:{controller.step}",
                    controller,
                )
                self.snapshot().submit(receipt.outcome.proposal)
                committed += 1
            except CharacterContextPending:
                self.controllers.defer(controller, "character_context_pending", pending=True)
            except (ValueError, PermissionError, KernelError):
                # Diagnostic details may contain hidden state. Store a stable operator code.
                self.controllers.defer(controller, "action_failed")
        return committed

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(0.25)

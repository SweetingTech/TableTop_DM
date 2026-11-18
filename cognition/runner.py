"""Bounded unattended decisions through the normal authorized kernel command path."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import Literal

from cognition.behavior import BehaviorProfile
from cognition.character_decisions import (
    CharacterContextPending,
    CharacterProposalReceipt,
    CharacterProposalRepository,
    CharacterProposalScope,
    propose_for_character,
    require_character_proposal_authority,
    require_projected_character_experience,
)
from cognition.character_plans import CharacterPlan, select_character_plan
from cognition.choices import ChoiceProfile
from cognition.context import CharacterContext
from cognition.control import REPLAN_LIMIT, ControllerRepository
from cognition.conversation import due_reply
from cognition.deliberation import DeliberationProvider
from cognition.dialogue_generation import DialogueProvider
from cognition.recovery import CharacterStalled, progress_constraints
from cognition.store import MindStore
from domains.tabletop.action_time import wait_seconds
from domains.tabletop.character_bindings import CharacterBinding, CharacterBindingRepository
from domains.tabletop.character_context import ProfileReader, resolve_character_context
from domains.tabletop.portal import PortalRepository
from domains.tabletop.rules import incapacitated
from domains.tabletop.spatial.service import build_perceived_scene
from kernel.application import SimulationApplication
from kernel.contracts import ActorKind
from kernel.control import ControllerState, ControlScope
from kernel.errors import (
    ActionRejectedAtRevision,
    BodyActionPending,
    BodyIncapacitated,
    BodyOutsideRelevance,
    BodySleeping,
    KernelError,
    WorldClockPaused,
)
from persona.models import CompiledPersona
from population.routines import uses_offscreen_routine


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
        behavior_reader: Callable[
            [
                SimulationApplication,
                ControlScope,
                uuid.UUID,
                CharacterContext,
                CharacterBinding,
                CompiledPersona,
            ],
            BehaviorProfile,
        ]
        | None = None,
        choice_reader: Callable[..., ChoiceProfile] | None = None,
        dialogue_provider: DialogueProvider | None = None,
        deliberation_provider: DeliberationProvider | None = None,
        deliberation_kind: Literal["LOCAL_LLM", "HOSTED_LLM"] = "HOSTED_LLM",
    ) -> None:
        self.snapshot, self.read_minds = snapshot, read_minds
        self.bindings, self.cards, self.profiles = bindings, cards, profiles
        self.proposals, self.reference = proposals, reference
        self.behavior_reader = behavior_reader
        self.choice_reader = choice_reader
        self.dialogue_provider = dialogue_provider
        self.deliberation_provider = deliberation_provider
        self.deliberation_kind = deliberation_kind

    def _previous_plan(
        self,
        source: SimulationApplication,
        controller: ControllerState,
        scope: CharacterProposalScope,
        binding: CharacterBinding,
    ) -> tuple[CharacterPlan, uuid.UUID] | None:
        if controller.step == 0:
            return None
        for record in reversed(source.command_history.get(controller.branch_id, [])):
            command = record.proposal
            if (
                command.world_id == controller.world_id
                and command.run_id == controller.run_id
                and command.actor_id == controller.executor_actor_id
                and command.embodied_entity_id == controller.entity_id
                and command.decision_authorship == "CHARACTER_POLICY"
                and command.control_epoch == controller.epoch
                and command.control_step == controller.step - 1
                and command.decision_trace_id is not None
                and record.result.accepted
            ):
                prior = self.proposals.find_decision(
                    scope, controller.executor_actor_id, command.decision_trace_id
                )
                if (
                    prior is not None
                    and prior.binding_id == binding.binding_id
                    and prior.outcome.proposal.command_id == command.command_id
                    and prior.plan is not None
                ):
                    return prior.plan, command.command_id
                break
        return None

    def decide(
        self,
        scope: ControlScope,
        actor_id: uuid.UUID,
        key: str,
        controller: ControllerState | None = None,
    ) -> CharacterProposalReceipt:
        proposal_scope = CharacterProposalScope.model_validate(scope.model_dump())
        reference = self.reference

        def prepare() -> Callable[[], CharacterProposalReceipt]:
            source = self.snapshot()
            require_character_proposal_authority(source, proposal_scope, actor_id)
            if source.runs[scope.run_id].status not in {"ACTIVE", "RUNNING"}:
                raise ValueError("character proposals require an active run")
            branch = source.states.get(scope.branch_id)
            if controller is not None and uses_offscreen_routine(branch, scope.entity_id):
                raise BodyOutsideRelevance("body is following its background routine")
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
            body = branch.projections.get("tabletop.entities", {}).get(str(scope.entity_id), {})
            if incapacitated(body):
                raise BodyIncapacitated("body is incapacitated")
            if wait_seconds(branch, scope.entity_id):
                raise BodyActionPending("body is still completing its previous action")
            plan = (
                select_character_plan(
                    resolved.context,
                    controller,
                    hunger=max(0, int(body.get("hunger", 0))),
                    fatigue=max(0, int(body.get("fatigue", 0))),
                    previous=self._previous_plan(
                        source, controller, proposal_scope, resolved.binding
                    ),
                )
                if controller is not None
                else None
            )
            reply = None
            recovery = None
            if controller is not None:
                reply = due_reply(
                    resolved.context, controller, source.events.get, now=datetime.now(UTC)
                )
                recovery = progress_constraints(
                    controller,
                    resolved.context,
                    source.command_history.get(scope.branch_id, ()),
                    reply,
                    source.events.get,
                )
            entity = source.entities[(scope.branch_id, scope.entity_id)]
            owner = (
                source.actors.get(entity.controller_actor_id)
                if entity.controller_actor_id
                else None
            )
            return partial(
                propose_for_character,
                scope=proposal_scope,
                actor_id=actor_id,
                key=key,
                run_seed=source.runs[scope.run_id].seed,
                context=resolved.context,
                binding=resolved.binding,
                profile=resolved.profile,
                controller=controller,
                stand_in=(
                    entity.entity_type == "PLAYER_CHARACTER"
                    and owner is not None
                    and owner.kind is ActorKind.HUMAN
                ),
                dialogue_provider=self.dialogue_provider,
                deliberation_provider=self.deliberation_provider,
                deliberation_kind=self.deliberation_kind,
                plan=plan,
                reply=reply,
                recovery_constraints=recovery,
                human_epoch=source.controller_states[scope.key].epoch
                if scope.key in source.controller_states
                else None,
                behavior=self.behavior_reader(
                    source, scope, actor_id, resolved.context, resolved.binding, resolved.profile
                )
                if self.behavior_reader
                else None,
                choices=self.choice_reader(
                    source, scope, actor_id, resolved.context, resolved.binding, resolved.profile
                )
                if self.choice_reader
                else None,
            )

        def generate() -> CharacterProposalReceipt:
            decision = reference.read_reference(prepare) if reference else prepare()
            receipt = decision()
            if reference is not None:
                current = reference.read_reference(
                    lambda: self.bindings.latest(scope.key, actor_id=actor_id)
                )
                if current is None or current.binding_id != receipt.binding_id:
                    raise ValueError("character binding changed while preparing the proposal")
            return receipt

        def check_reference() -> None:
            if reference is not None:
                reference.read_reference(
                    lambda: require_character_proposal_authority(
                        reference, proposal_scope, actor_id
                    )
                )

        check_reference()
        receipt = self.proposals.get_or_create(proposal_scope, actor_id, key, generate)
        check_reference()
        return receipt


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
                source = self.snapshot()
                clock = (
                    source.states.get(controller.branch_id)
                    .projections.get("tabletop.clock", {})
                    .get("singleton")
                )
                if clock is not None and clock["paused"]:
                    continue
                body = (
                    source.states.get(controller.branch_id)
                    .projections.get("tabletop.entities", {})
                    .get(str(controller.entity_id), {})
                )
                if body.get("asleep") or incapacitated(body):
                    continue
                if wait_seconds(source.states.get(controller.branch_id), controller.entity_id):
                    continue
                receipt = self.decisions.decide(
                    controller.scope,
                    controller.executor_actor_id,
                    controller.decision_key,
                    controller,
                )
                try:
                    self.snapshot().submit(receipt.outcome.proposal)
                except ActionRejectedAtRevision as error:
                    if error.revision <= receipt.projection_version:
                        raise
                    self.controllers.defer(
                        controller, "action_invalidated", retry_limit=REPLAN_LIMIT
                    )
                    continue
                committed += 1
            except BodyOutsideRelevance:
                self.controllers.defer(controller, None)
            except (WorldClockPaused, BodySleeping, BodyIncapacitated, BodyActionPending):
                # Pause may win after the initial check, including during model generation.
                # Keep epoch/step, mode and failure budget intact for clock resume.
                continue
            except CharacterContextPending:
                self.controllers.defer(controller, "character_context_pending", retry_limit=39)
            except CharacterStalled as error:
                self.controllers.defer(controller, error.reason)
            except (ValueError, PermissionError, KernelError):
                # Diagnostic details may contain hidden state. Store a stable operator code.
                self.controllers.defer(controller, "action_failed")
        return committed

    def run_forever(self) -> None:
        while True:
            self.run_once()
            time.sleep(0.25)

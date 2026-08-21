from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from kernel.contracts import (
    Actor,
    BranchKind,
    CommandProposal,
    CommandResult,
    EventEnvelopeV2,
)
from kernel.errors import AuthorizationDenied, UnknownCommand
from kernel.event_factory import EmissionBuilder, EventFactory
from kernel.perception_contracts import PerceptionGrant
from kernel.state import BranchState, InMemoryStateStore

CommandHandler = Callable[[CommandProposal, BranchState], CommandResult]


@dataclass(frozen=True)
class CommandDefinition:
    command_type: str
    required_capabilities: frozenset[str]
    allowed_branch_kinds: frozenset[BranchKind]
    handler: CommandHandler
    version: str = "1.0.0"
    request_model: type[BaseModel] | None = None
    result_model: type[BaseModel] | None = None
    sensitive_parameters: frozenset[str] = frozenset()
    requires_controlled_entity: bool = False
    emission_builder: EmissionBuilder | None = None


@dataclass(frozen=True)
class CommandReceipt:
    result: CommandResult
    event: EventEnvelopeV2
    state_hash: str
    perceptions: tuple[PerceptionGrant, ...] = ()


class CommandBus:
    """Deny-by-default command authority and deterministic mutation boundary."""

    def __init__(
        self,
        states: InMemoryStateStore,
        event_factory: EventFactory | None = None,
    ) -> None:
        self.states = states
        self.event_factory = event_factory or EventFactory()
        self._definitions: dict[str, CommandDefinition] = {}
        self._receipts: dict[tuple[uuid.UUID, uuid.UUID, str], CommandReceipt] = {}

    def register(self, definition: CommandDefinition) -> None:
        if definition.command_type in self._definitions:
            raise ValueError(f"Command already registered: {definition.command_type}")
        self._definitions[definition.command_type] = definition

    def definition(self, command_type: str) -> CommandDefinition:
        try:
            return self._definitions[command_type]
        except KeyError as exc:
            raise UnknownCommand(command_type) from exc

    def execute(self, proposal: CommandProposal, actor: Actor) -> CommandReceipt:
        if proposal.actor_id != actor.actor_id:
            raise AuthorizationDenied("Proposal actor does not match authenticated actor")
        definition = self._definitions.get(proposal.command_type)
        if definition is None:
            raise UnknownCommand(proposal.command_type)
        if not actor.has_capabilities(definition.required_capabilities):
            raise AuthorizationDenied(
                "Missing capabilities: "
                f"{sorted(definition.required_capabilities - actor.capabilities)}"
            )
        if definition.requires_controlled_entity and proposal.embodied_entity_id is None:
            raise AuthorizationDenied("Command requires an embodied entity")
        if (
            definition.requires_controlled_entity
            and proposal.embodied_entity_id not in actor.controlled_entity_ids
        ):
            raise AuthorizationDenied("Actor does not control the embodied entity")
        if definition.request_model is not None:
            try:
                normalized = definition.request_model.model_validate(
                    proposal.parameters
                ).model_dump(mode="python")
            except ValidationError as exc:
                raise ValueError(f"Invalid {proposal.command_type} parameters") from exc
            proposal = proposal.model_copy(update={"parameters": normalized})
        key = (proposal.run_id, proposal.actor_id, proposal.idempotency_key)

        def run(state: BranchState) -> CommandReceipt:
            if state.world_id != proposal.world_id:
                raise AuthorizationDenied("Branch does not belong to proposal world")
            if state.kind not in definition.allowed_branch_kinds:
                raise AuthorizationDenied(
                    f"{proposal.command_type} is not allowed on {state.kind.value} branches"
                )
            branch_capability = (
                "action.commit" if state.kind is BranchKind.CANONICAL else "action.propose"
            )
            if branch_capability not in actor.capabilities:
                raise AuthorizationDenied(f"Missing capabilities: ['{branch_capability}']")
            before = state.working_copy()
            result = definition.handler(proposal, state)
            if definition.result_model is not None:
                definition.result_model.model_validate(result.result)
            for delta in result.deltas:
                state.apply(delta)
            materialized = self.event_factory.materialize(
                proposal=proposal,
                result=result,
                before=before,
                after=state,
                emission_builder=definition.emission_builder,
            )
            return CommandReceipt(
                result=result,
                event=materialized.event,
                state_hash=state.state_hash,
                perceptions=materialized.perceptions,
            )

        receipt, _duplicate = self.states.execute_atomic(proposal.branch_id, key, run)
        return receipt

    def contracts(self) -> tuple[dict[str, Any], ...]:
        """Expose registered command contracts for UIs and agent runtimes."""
        contracts = []
        for command_type, definition in sorted(self._definitions.items()):
            contracts.append(
                {
                    "command_type": command_type,
                    "version": definition.version,
                    "required_capabilities": sorted(definition.required_capabilities),
                    "allowed_branch_kinds": sorted(
                        item.value for item in definition.allowed_branch_kinds
                    ),
                    "sensitive_parameters": sorted(definition.sensitive_parameters),
                    "requires_controlled_entity": definition.requires_controlled_entity,
                    "request_schema": definition.request_model.model_json_schema()
                    if definition.request_model
                    else {"type": "object"},
                    "result_schema": definition.result_model.model_json_schema()
                    if definition.result_model
                    else {"type": "object"},
                }
            )
        return tuple(contracts)

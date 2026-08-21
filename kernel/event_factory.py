from __future__ import annotations

import uuid
from collections.abc import Callable

from kernel.contracts import CommandProposal, CommandResult, EventEnvelopeV2
from kernel.perception_contracts import (
    EventEmission,
    EventMaterialization,
    NullSpatialPerceptionResolver,
    SpatialPerceptionResolver,
)
from kernel.state import BranchState

EmissionBuilder = Callable[
    [CommandProposal, CommandResult, BranchState, BranchState], EventEmission | None
]


def stable_event_id(proposal: CommandProposal) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"tabletop-dm:event:{proposal.run_id}:{proposal.actor_id}:{proposal.idempotency_key}",
    )


class EventFactory:
    """One event/perception materializer shared by reference and durable execution."""

    def __init__(self, resolver: SpatialPerceptionResolver | None = None) -> None:
        self.resolver = resolver or NullSpatialPerceptionResolver()

    def materialize(
        self,
        *,
        proposal: CommandProposal,
        result: CommandResult,
        before: BranchState,
        after: BranchState,
        emission_builder: EmissionBuilder | None,
    ) -> EventMaterialization:
        event_id = stable_event_id(proposal)
        emission = (
            emission_builder(proposal, result, before, after)
            if emission_builder is not None
            else None
        )
        resolution = self.resolver.resolve(
            event_id=event_id,
            proposal=proposal,
            emission=emission,
            before=before,
            after=after,
        )
        event = EventEnvelopeV2(
            event_id=event_id,
            world_id=proposal.world_id,
            branch_id=proposal.branch_id,
            run_id=proposal.run_id,
            interaction_id=proposal.interaction_id,
            actor_id=proposal.actor_id,
            embodied_entity_id=proposal.embodied_entity_id,
            event_type=proposal.command_type,
            payload=result.result,
            observed_by=resolution.controller_actor_summary,
            # Physical witnesses receive subjective observations, never raw truth.
            visible_to=(proposal.actor_id,),
            correlation_id=proposal.correlation_id,
            causation_id=proposal.causation_id,
            domain_tags=result.domain_tags,
            idempotency_key=proposal.idempotency_key,
            seed=proposal.seed,
            decision_trace_id=proposal.decision_trace_id,
            persona_version=proposal.persona_version,
            policy_version=proposal.policy_version,
            prompt_contract_version=proposal.prompt_contract_version,
            model_version=proposal.model_version,
        )
        return EventMaterialization(event=event, perceptions=resolution.perceptions)

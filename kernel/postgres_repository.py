from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2.errors
import psycopg2.extras
from pydantic import ValidationError

from kernel.command_bus import CommandDefinition, CommandReceipt
from kernel.contracts import (
    Actor,
    BranchKind,
    CommandProposal,
    CommandResult,
    EventEnvelopeV2,
)
from kernel.database import transaction
from kernel.errors import AuthorizationDenied, BranchIsolationError
from kernel.state import BranchState


class PostgresCommandRepository:
    """Persist projection, command, event, and outbox as one transaction."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn

    def execute(
        self,
        proposal: CommandProposal,
        actor: Actor,
        definition: CommandDefinition,
    ) -> CommandReceipt:
        if proposal.actor_id != actor.actor_id:
            raise AuthorizationDenied("Proposal actor does not match authenticated actor")
        if definition.command_type != proposal.command_type:
            raise ValueError("Command definition does not match proposal")
        if definition.request_model is not None:
            try:
                parameters = definition.request_model.model_validate(
                    proposal.parameters
                ).model_dump(mode="python")
            except ValidationError as exc:
                raise ValueError(f"Invalid {proposal.command_type} parameters") from exc
            proposal = proposal.model_copy(update={"parameters": parameters})

        try:
            return self._execute_once(proposal, actor, definition)
        except psycopg2.errors.UniqueViolation:
            receipt = self._load_receipt(proposal)
            if receipt is None:
                raise
            return receipt

    def _execute_once(
        self,
        proposal: CommandProposal,
        actor: Actor,
        definition: CommandDefinition,
    ) -> CommandReceipt:
        with transaction(actor_id=actor.actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT world_id, branch_kind, status
                    FROM sim.branches
                    WHERE world_id = %s AND id = %s
                    FOR UPDATE
                    """,
                    (str(proposal.world_id), str(proposal.branch_id)),
                )
                branch = cursor.fetchone()
                if branch is None:
                    raise BranchIsolationError("Unknown branch or world mismatch")

                cursor.execute(
                    """
                    SELECT 1
                    FROM sim.runs
                    WHERE world_id = %s AND branch_id = %s AND id = %s
                    """,
                    (
                        str(proposal.world_id),
                        str(proposal.branch_id),
                        str(proposal.run_id),
                    ),
                )
                if cursor.fetchone() is None:
                    raise BranchIsolationError("Proposal run does not belong to the world branch")
                if proposal.interaction_id is not None:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM sim.interactions
                        WHERE world_id = %s AND branch_id = %s
                          AND run_id = %s AND id = %s
                        """,
                        (
                            str(proposal.world_id),
                            str(proposal.branch_id),
                            str(proposal.run_id),
                            str(proposal.interaction_id),
                        ),
                    )
                    if cursor.fetchone() is None:
                        raise BranchIsolationError(
                            "Proposal interaction does not belong to the run"
                        )

                existing = self._load_receipt_with_cursor(cursor, proposal)
                if existing is not None:
                    return existing

                kind = BranchKind(str(branch["branch_kind"]))
                if kind not in definition.allowed_branch_kinds:
                    raise AuthorizationDenied(
                        f"{proposal.command_type} is not allowed on {kind.value} branches"
                    )
                required = set(definition.required_capabilities)
                required.add("action.commit" if kind is BranchKind.CANONICAL else "action.propose")
                cursor.execute(
                    """
                    SELECT capability
                    FROM sim.actor_capabilities
                    WHERE world_id = %s AND actor_id = %s
                      AND capability = ANY(%s::text[])
                    """,
                    (
                        str(proposal.world_id),
                        str(actor.actor_id),
                        sorted(required),
                    ),
                )
                durable = {str(row["capability"]) for row in cursor.fetchall()}
                missing = required - durable
                if missing:
                    raise AuthorizationDenied(
                        f"Durable actor lacks capabilities: {sorted(missing)}"
                    )

                if proposal.embodied_entity_id is not None and "entity.control" in required:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM sim.entities
                        WHERE world_id = %s AND branch_id = %s AND id = %s
                          AND controller_actor_id = %s
                        """,
                        (
                            str(proposal.world_id),
                            str(proposal.branch_id),
                            str(proposal.embodied_entity_id),
                            str(actor.actor_id),
                        ),
                    )
                    if cursor.fetchone() is None:
                        raise AuthorizationDenied("Actor does not control the embodied entity")

                cursor.execute(
                    """
                    SELECT version, state
                    FROM sim.branch_projections
                    WHERE world_id = %s AND branch_id = %s
                    FOR UPDATE
                    """,
                    (str(proposal.world_id), str(proposal.branch_id)),
                )
                projection = cursor.fetchone()
                if projection is None:
                    raise BranchIsolationError("Branch projection is missing")
                state = BranchState(
                    world_id=proposal.world_id,
                    branch_id=proposal.branch_id,
                    kind=kind,
                    projections=dict(projection["state"]),
                    version=int(projection["version"]),
                )

                result = definition.handler(proposal, state)
                if definition.result_model is not None:
                    definition.result_model.model_validate(result.result)
                for delta in result.deltas:
                    state.apply(delta)
                self._apply_entity_mutations(cursor, proposal, result)
                next_version = state.version + 1
                state_hash = state.state_hash
                event = self._event(proposal, result)

                cursor.execute(
                    """
                    UPDATE sim.branch_projections
                    SET version = %s, state = %s::jsonb, state_hash = %s,
                        updated_at = now()
                    WHERE world_id = %s AND branch_id = %s AND version = %s
                    """,
                    (
                        next_version,
                        json.dumps(state.projections, default=str),
                        state_hash,
                        str(proposal.world_id),
                        str(proposal.branch_id),
                        state.version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise BranchIsolationError("Branch projection version changed")

                ledger_parameters = dict(proposal.parameters)
                for name in definition.sensitive_parameters:
                    if name in ledger_parameters:
                        ledger_parameters[name] = "[REDACTED]"
                cursor.execute(
                    """
                    INSERT INTO sim.command_log (
                      command_id, command_type, command_version, world_id,
                      branch_id, run_id, interaction_id, actor_id,
                      embodied_entity_id, parameters, result, seed,
                      idempotency_key, correlation_id, causation_id,
                      resulting_state_hash
                    ) VALUES (
                      %s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,
                      %s,%s,%s,%s
                    )
                    """,
                    (
                        str(proposal.command_id),
                        proposal.command_type,
                        definition.version,
                        str(proposal.world_id),
                        str(proposal.branch_id),
                        str(proposal.run_id),
                        str(proposal.interaction_id) if proposal.interaction_id else None,
                        str(proposal.actor_id),
                        str(proposal.embodied_entity_id) if proposal.embodied_entity_id else None,
                        json.dumps(ledger_parameters, default=str),
                        result.model_dump_json(),
                        proposal.seed,
                        proposal.idempotency_key,
                        str(proposal.correlation_id),
                        str(proposal.causation_id) if proposal.causation_id else None,
                        state_hash,
                    ),
                )
                self._insert_event(cursor, event)
                cursor.execute(
                    """
                    INSERT INTO sim.outbox (event_id, topic, payload)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (
                        str(event.event_id),
                        f"world.{event.world_id}.branch.{event.branch_id}",
                        event.model_dump_json(),
                    ),
                )
                return CommandReceipt(result=result, event=event, state_hash=state_hash)

    @staticmethod
    def _apply_entity_mutations(
        cursor: Any, proposal: CommandProposal, result: CommandResult
    ) -> None:
        for mutation in result.entity_mutations:
            if mutation.operation != "CREATE":
                raise ValueError(f"Unsupported entity mutation: {mutation.operation}")
            cursor.execute(
                """
                INSERT INTO sim.entities (
                  id, world_id, branch_id, entity_type, name,
                  public_state, secret_state, controller_actor_id
                ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s)
                """,
                (
                    str(mutation.entity_id),
                    str(proposal.world_id),
                    str(proposal.branch_id),
                    mutation.entity_type,
                    mutation.name,
                    json.dumps(mutation.public_state, default=str),
                    json.dumps(mutation.secret_state, default=str),
                    str(mutation.controller_actor_id) if mutation.controller_actor_id else None,
                ),
            )

    def _load_receipt(self, proposal: CommandProposal) -> CommandReceipt | None:
        with transaction(actor_id=proposal.actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                return self._load_receipt_with_cursor(cursor, proposal)

    @staticmethod
    def _load_receipt_with_cursor(cursor: Any, proposal: CommandProposal) -> CommandReceipt | None:
        cursor.execute(
            """
            SELECT c.result, c.resulting_state_hash, e.*,
                   e.observed_by::text[] AS observed_by,
                   e.visible_to::text[] AS visible_to
            FROM sim.command_log c
            JOIN sim.events e
              ON e.run_id = c.run_id
             AND e.actor_id = c.actor_id
             AND e.idempotency_key = c.idempotency_key
            WHERE c.run_id = %s AND c.actor_id = %s
              AND c.idempotency_key = %s
            """,
            (
                str(proposal.run_id),
                str(proposal.actor_id),
                proposal.idempotency_key,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        result = CommandResult.model_validate(row["result"])
        event_fields = set(EventEnvelopeV2.model_fields)
        event_payload = {key: row[key] for key in event_fields if key in row}
        event_payload["observed_by"] = tuple(row["observed_by"] or ())
        event_payload["visible_to"] = tuple(row["visible_to"] or ())
        event_payload["domain_tags"] = tuple(row["domain_tags"] or ())
        return CommandReceipt(
            result=result,
            event=EventEnvelopeV2.model_validate(event_payload),
            state_hash=str(row["resulting_state_hash"]),
        )

    @staticmethod
    def _event(proposal: CommandProposal, result: CommandResult) -> EventEnvelopeV2:
        return EventEnvelopeV2(
            event_id=uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"tabletop-dm:event:{proposal.run_id}:{proposal.actor_id}:{proposal.idempotency_key}",
            ),
            world_id=proposal.world_id,
            branch_id=proposal.branch_id,
            run_id=proposal.run_id,
            interaction_id=proposal.interaction_id,
            actor_id=proposal.actor_id,
            embodied_entity_id=proposal.embodied_entity_id,
            event_type=proposal.command_type,
            payload=result.result,
            # Empty means perception is not pre-limited to a materialized
            # audience. Visibility authorization is still enforced first.
            observed_by=(),
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

    @staticmethod
    def _insert_event(cursor: Any, event: EventEnvelopeV2) -> None:
        cursor.execute(
            """
            INSERT INTO sim.events (
              event_id, event_version, contract_version, world_id, branch_id,
              run_id, interaction_id, actor_id, embodied_entity_id, event_type,
              payload, observed_by, visible_to, parent_event_id, correlation_id,
              causation_id, domain_tags, idempotency_key, persona_version,
              policy_version, prompt_contract_version, model_version, seed,
              decision_trace_id, created_at
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::uuid[],%s::uuid[],
              %s,%s,%s,%s::text[],%s,%s,%s,%s,%s,%s,%s,%s
            )
            """,
            (
                str(event.event_id),
                event.event_version,
                event.contract_version,
                str(event.world_id),
                str(event.branch_id),
                str(event.run_id),
                str(event.interaction_id) if event.interaction_id else None,
                str(event.actor_id),
                str(event.embodied_entity_id) if event.embodied_entity_id else None,
                event.event_type,
                json.dumps(event.payload, default=str),
                [str(value) for value in event.observed_by],
                [str(value) for value in event.visible_to],
                str(event.parent_event_id) if event.parent_event_id else None,
                str(event.correlation_id),
                str(event.causation_id) if event.causation_id else None,
                list(event.domain_tags),
                event.idempotency_key,
                event.persona_version,
                event.policy_version,
                event.prompt_contract_version,
                event.model_version,
                event.seed,
                str(event.decision_trace_id) if event.decision_trace_id else None,
                event.created_at,
            ),
        )

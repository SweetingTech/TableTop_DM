# ruff: noqa: E501 -- SQL statements retain one-to-one column/value alignment.
from __future__ import annotations

import uuid
from collections.abc import Callable

import psycopg2.extras

from cognition.character_decisions import CharacterProposalReceipt, CharacterProposalScope
from cognition.postgres import PostgresMindRepository
from kernel.database import transaction


class PostgresCharacterProposals:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def get_or_create(
        self,
        scope: CharacterProposalScope,
        actor_id: uuid.UUID,
        key: str,
        factory: Callable[[], CharacterProposalReceipt],
    ) -> CharacterProposalReceipt:
        try:
            return self._get_or_create(scope, actor_id, key, factory)
        except psycopg2.errors.InsufficientPrivilege:
            raise PermissionError("actor cannot propose for this character") from None
        except psycopg2.Error:
            raise ValueError(
                "character proposal could not be stored; retry the same request"
            ) from None

    def _get_or_create(
        self,
        scope: CharacterProposalScope,
        actor_id: uuid.UUID,
        key: str,
        factory: Callable[[], CharacterProposalReceipt],
    ) -> CharacterProposalReceipt:
        with transaction(actor_id=actor_id, dsn=self.dsn) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                # Match the binding writer's run lock before the kernel's branch lock.
                # Do not lock arbitrary worlds for an unauthorized caller.
                cursor.execute(
                    """
                    SELECT r.id FROM sim.runs r WHERE (r.world_id,r.branch_id,r.id)=(%s,%s,%s)
                    AND sim.has_world_capability(r.world_id,'action.propose')
                    AND sim.has_world_capability(r.world_id,'entity.act')
                    AND sim.can_mutate_branch(r.world_id,r.branch_id)
                    AND EXISTS (SELECT 1 FROM sim.entities e WHERE (e.world_id,e.branch_id,e.id)=(r.world_id,r.branch_id,%s)
                      AND e.controller_actor_id=sim.current_actor_id()) FOR UPDATE
                    """,
                    tuple(map(str, scope.key)),
                )
                if cursor.fetchone() is None:
                    raise PermissionError("actor cannot propose for this character")
                cursor.execute(
                    "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
                    (str(scope.world_id), str(scope.branch_id)),
                )
                cursor.execute(
                    "SELECT payload FROM cognition.character_proposal_receipts WHERE (world_id,branch_id,run_id,entity_id,actor_id,idempotency_key)=(%s,%s,%s,%s,%s,%s)",
                    (*map(str, scope.key), str(actor_id), key),
                )
                previous = cursor.fetchone()
                if previous:
                    return CharacterProposalReceipt.model_validate(previous["payload"])
                receipt = factory()
                if (receipt.scope, receipt.actor_id, receipt.idempotency_key) != (
                    scope,
                    actor_id,
                    key,
                ):
                    raise ValueError("character proposal receipt scope differs from its request")
                PostgresMindRepository(self.dsn).save_decision(
                    receipt.outcome, connection=connection
                )
                cursor.execute(
                    """INSERT INTO cognition.character_proposal_receipts
                    (decision_id,world_id,branch_id,run_id,entity_id,actor_id,idempotency_key,character_id,binding_id,
                     context_hash,projection_version,seed,payload,created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)""",
                    (
                        str(receipt.decision_id),
                        *map(str, scope.key),
                        str(actor_id),
                        key,
                        str(receipt.character_id),
                        str(receipt.binding_id),
                        receipt.context_hash,
                        receipt.projection_version,
                        receipt.seed,
                        receipt.model_dump_json(),
                        receipt.created_at,
                    ),
                )
                return receipt

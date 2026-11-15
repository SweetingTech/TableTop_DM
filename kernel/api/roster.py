"""Finish one roster edit and its body grants as a recoverable logical operation."""

from __future__ import annotations

import uuid

from domains.tabletop.portal import GameMember, TabletopPortalService
from identity.models import UserAccount
from identity.service import IdentityService
from kernel.application import SimulationApplication
from kernel.contracts import CommandProposal, RunKind
from kernel.database import unit_of_work


def finalize_member(
    simulation: SimulationApplication,
    portal: TabletopPortalService,
    actor: UserAccount,
    game_id: uuid.UUID,
    user_id: uuid.UUID,
    member: GameMember | None,
    *,
    target_entity_id: uuid.UUID | None = None,
    dsn: str | None = None,
) -> None:
    """Keep the physical body/mind, revoke the removed seat and pause its runner.

    Another game's assignment preserves its grant. World roles are independent.
    Preparation is retryable and grants no player control before finalization.
    """
    game = portal._hosted(actor, game_id)
    IdentityService.require_world_role(actor, game.world_id, "DM")
    branch_id = simulation.worlds[game.world_id].canonical_branch_id

    def finish(connection=None):
        if connection is not None:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM sim.branches WHERE (world_id,id)=(%s,%s) FOR UPDATE",
                    (str(game.world_id), str(branch_id)),
                )
                if cursor.fetchone() is None:
                    raise ValueError("world branch is unavailable")
        previous_game = portal._hosted(actor, game_id)
        previous = next((row for row in previous_game.members if row.user_id == user_id), None)
        desired: dict[uuid.UUID, uuid.UUID | None] = {}
        if (
            previous
            and previous.character_id
            and (member is None or previous.character_id != member.character_id)
        ):
            card = portal.repository.get_character(previous.character_id)
            shared = any(
                other.game_id != game_id
                and other.world_id == game.world_id
                and any(row.character_id == previous.character_id for row in other.members)
                for other in portal.repository.list_games()
            )
            if card and card.entity_id and not shared:
                desired[card.entity_id] = None
        if target_entity_id is not None:
            account = portal.identities.get_account(user_id)
            if account is None or not account.is_active:
                raise ValueError("member account is unavailable")
            desired[target_entity_id] = account.actor_id
        changes = []
        for entity_id, controller in sorted(desired.items(), key=lambda pair: str(pair[0])):
            if connection is None:
                body = simulation.entities.get((branch_id, entity_id))
                if body is None or body.world_id != game.world_id:
                    raise ValueError("member body is unavailable")
                current = body.controller_actor_id
            else:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT controller_actor_id FROM sim.entities "
                        "WHERE (world_id,branch_id,id)=(%s,%s,%s)",
                        (str(game.world_id), str(branch_id), str(entity_id)),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise ValueError("member body is unavailable")
                    current = uuid.UUID(str(row[0])) if row[0] else None
            if current != controller:
                changes.append({"entity_id": entity_id, "controller_actor_id": controller})

        def publish():
            if member is None:
                portal.repository.remove_member(game_id, user_id)
            else:
                portal.repository.set_member(game_id, member)

        if not changes:
            publish()
            return
        live_run = next(
            (
                run
                for run in simulation.runs.values()
                if (run.world_id, run.branch_id) == (game.world_id, branch_id)
                and run.kind is RunKind.LIVE
                and run.status in {"ACTIVE", "RUNNING", "PAUSED", "QUEUED"}
            ),
            None,
        )
        if live_run is None:
            raise ValueError("start an unfinished live run before changing character control")
        proposal = CommandProposal(
            command_type="tabletop.entity.set_controllers",
            world_id=game.world_id,
            branch_id=branch_id,
            run_id=live_run.run_id,
            actor_id=actor.actor_id,
            parameters={"changes": changes},
            idempotency_key=f"roster-control:{uuid.uuid4()}",
        )
        if connection is not None:
            publish()
            simulation.submit(proposal)
        else:
            version = simulation.states.get(branch_id).version
            try:
                simulation.submit(proposal, before_reference_commit=publish)
            except BaseException:
                if simulation.states.get(branch_id).version == version:
                    portal.repository.save_game(previous_game)
                raise

    if dsn is None:
        simulation.read_reference(finish)
    else:
        with unit_of_work(actor_id=actor.actor_id, dsn=dsn) as connection:
            finish(connection)

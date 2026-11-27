"""Shared plans and donated resources with individual control of movement."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from domains.tabletop.economy import body, usable_inventory
from domains.tabletop.parties import (
    Party,
    PartyEvent,
    PartyReference,
    PartySupplyCache,
    PartyWaypoint,
    party_contact,
    party_result,
    read_party,
    set_party,
)
from kernel.command_bus import CommandDefinition, CommandHandler
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.event_factory import stable_event_id
from kernel.state import BranchState


class PlanParty(PartyReference):
    goal: str = Field(min_length=1, max_length=400)
    waypoint: PartyWaypoint | None = None


class FollowPlan(PartyReference):
    plan_event_id: uuid.UUID
    follow: bool = Field(strict=True)


class TransferLeadership(PartyReference):
    successor_id: uuid.UUID


class ExchangeSupplies(PartyReference):
    direction: Literal["DEPOSIT", "WITHDRAW"]
    amount: int = Field(ge=1, le=1000000, strict=True)
    item: str | None = Field(default=None, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")


def _membership(
    proposal: CommandProposal, state: BranchState, party_id: uuid.UUID
) -> tuple[uuid.UUID, Party]:
    member = proposal.embodied_entity_id
    party = read_party(state, party_id)
    if member is None or member not in party.member_ids:
        raise ValueError("party is unavailable")
    return member, party


def plan_party(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = PlanParty.model_validate(proposal.parameters)
    member, party = _membership(proposal, state, request.party_id)
    if party.leader_id != member:
        raise ValueError("only the current leader can set the party plan")
    updated = party.model_copy(
        update={
            "goal": request.goal,
            "waypoint": request.waypoint,
            "plan_event_id": stable_event_id(proposal),
            "following_member_ids": (),
        }
    )
    return party_result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=member,
            kind="PLAN_UPDATED",
            summary="Set a new goal and travel plan for the party.",
        ),
        set_party(updated),
    )


def follow_plan(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = FollowPlan.model_validate(proposal.parameters)
    member, party = _membership(proposal, state, request.party_id)
    if party.plan_event_id != request.plan_event_id or party.waypoint is None:
        raise ValueError("party travel plan is unavailable")
    following = set(party.following_member_ids)
    if (member in following) == request.follow:
        raise ValueError("this character has already made that travel choice")
    if request.follow:
        following.add(member)
    else:
        following.remove(member)
    updated = party.model_copy(
        update={
            "following_member_ids": tuple(
                identity for identity in party.member_ids if identity in following
            ),
        }
    )
    return party_result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=member,
            kind="FOLLOWING" if request.follow else "STOPPED_FOLLOWING",
            summary="Agreed to travel to the waypoint."
            if request.follow
            else "Stopped following the travel plan.",
        ),
        set_party(updated),
    )


def transfer_leadership(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = TransferLeadership.model_validate(proposal.parameters)
    member, party = _membership(proposal, state, request.party_id)
    if party.leader_id != member or request.successor_id not in party.member_ids:
        raise ValueError("leadership can pass only to a fellow member")
    party_contact(state, member, request.successor_id)
    updated = party.model_copy(update={"leader_id": request.successor_id})
    return party_result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=member,
            kind="LEADER_CHANGED",
            summary="Passed the party's leadership to a fellow member.",
        ),
        set_party(updated),
    )


def _cache_position(state: BranchState, member: uuid.UUID, active_body: dict) -> PartyWaypoint:
    spot = state.projections.get("tabletop.spatial.positions", {}).get(str(member), active_body)
    if "x" not in spot or "y" not in spot:
        raise ValueError("party resources require a physical cache location")
    return PartyWaypoint(
        x=int(spot["x"]),
        y=int(spot["y"]),
        z=int(spot.get("z", 0)),
        zone_id=str(spot.get("zone_id", "world")),
    )


def exchange_supplies(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ExchangeSupplies.model_validate(proposal.parameters)
    member, party = _membership(proposal, state, request.party_id)
    active_body = body(state, member)
    position = _cache_position(state, member, active_body)
    cache = party.supplies
    if (cache is None and request.direction == "WITHDRAW") or (
        cache is not None and position != cache.position
    ):
        raise ValueError("party supplies are unavailable at this location")
    cache = cache or PartySupplyCache(position=position)
    amount = request.amount if request.direction == "DEPOSIT" else -request.amount
    if request.item is None:
        body_gold, party_gold = int(active_body.get("gold", 0)) - amount, cache.gold + amount
        if body_gold < 0 or party_gold < 0:
            raise ValueError("insufficient gold for this transfer")
        changes = {"gold": body_gold}
        cache = cache.model_copy(update={"gold": party_gold})
    else:
        item = request.item
        remaining = cache.inventory.get(item, 0) + amount
        if remaining < 0:
            raise ValueError("insufficient supplies for this transfer")
        changes = usable_inventory(active_body, item, -amount)
        inventory = {**cache.inventory, item: remaining}
        cache = cache.model_copy(update={"inventory": {k: v for k, v in inventory.items() if v}})
    updated = party.model_copy(
        update={"supplies": cache if cache.gold or cache.inventory else None}
    )
    return party_result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=member,
            kind="SUPPLIES_MOVED",
            summary="Contributed to the party's cache."
            if amount > 0
            else "Collected supplies from the party's cache.",
        ),
        set_party(updated),
        StateDelta(
            projection="tabletop.entities",
            entity_id=member,
            operation="MERGE",
            values=changes,
        ),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    commands: tuple[tuple[str, type[PartyReference], CommandHandler], ...] = (
        ("plan", PlanParty, plan_party),
        ("follow", FollowPlan, follow_plan),
        ("transfer_leadership", TransferLeadership, transfer_leadership),
        ("supplies", ExchangeSupplies, exchange_supplies),
    )
    return tuple(
        CommandDefinition(
            command_type=f"tabletop.party.{name}",
            required_capabilities=frozenset({"action.propose", "entity.act"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=request,
            result_model=PartyEvent,
            requires_controlled_entity=True,
        )
        for name, request, handler in commands
    )

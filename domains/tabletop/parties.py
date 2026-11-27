"""In-world membership and invitations. Control and perception remain separate."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.rules import capable
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandDefinition, CommandHandler
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.event_factory import stable_event_id
from kernel.state import BranchState

PARTIES = "tabletop.parties"
INVITATIONS = "tabletop.party_invitations"


class PartyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CreateParty(PartyModel):
    name: str = Field(min_length=1, max_length=100)
    goal: str = Field(min_length=1, max_length=400)
    motive: Literal["DUTY", "CURIOSITY", "CARE", "RECOVERY"] = "CARE"


class PartyReference(PartyModel):
    party_id: uuid.UUID


class InviteMember(PartyReference):
    invitee_id: uuid.UUID


class RespondToInvitation(PartyModel):
    invitation_id: uuid.UUID
    accept: bool = Field(strict=True)


class LeaveParty(PartyReference):
    reason: str = Field(min_length=1, max_length=400)
    hostile: bool = Field(default=False, strict=True)


class PartyView(CreateParty, PartyReference):
    leader_id: uuid.UUID | None
    member_ids: tuple[uuid.UUID, ...]


class Party(PartyView):
    departure_events: dict[uuid.UUID, uuid.UUID] = Field(default_factory=dict)


class InvitationView(CreateParty, InviteMember):
    invitation_id: uuid.UUID
    inviter_id: uuid.UUID


class Invitation(InvitationView):
    status: Literal["PENDING", "ACCEPTED", "DECLINED", "WITHDRAWN"] = "PENDING"


class PartyEvent(PartyReference):
    actor_entity_id: uuid.UUID
    kind: Literal["CREATED", "INVITED", "JOINED", "DECLINED", "LEFT", "HOSTILE_EXIT", "REUNITED"]
    invitation_id: uuid.UUID | None = None
    invitee_id: uuid.UUID | None = None
    prior_departure_event_id: uuid.UUID | None = None
    reason: str | None = None
    summary: str


def member_and_invitations(
    state: BranchState, observer: uuid.UUID
) -> tuple[tuple[PartyView, ...], tuple[InvitationView, ...]]:
    parties = tuple(
        PartyView.model_validate({key: raw[key] for key in PartyView.model_fields if key in raw})
        for _, raw in sorted(state.projections.get(PARTIES, {}).items())
        if str(observer) in raw["member_ids"]
    )
    invites = tuple(
        InvitationView.model_validate(
            {key: raw[key] for key in InvitationView.model_fields if key in raw}
        )
        for _, raw in sorted(state.projections.get(INVITATIONS, {}).items())
        if raw["status"] == "PENDING" and raw["invitee_id"] == str(observer)
    )
    return parties, invites


def _read_party(state: BranchState, identity: uuid.UUID) -> Party:
    raw = state.projections.get(PARTIES, {}).get(str(identity))
    if raw is None:
        raise ValueError("party is unavailable")
    return Party.model_validate(raw)


def _body(proposal: CommandProposal) -> uuid.UUID:
    if proposal.embodied_entity_id is None:
        raise ValueError("party action requires a body")
    return proposal.embodied_entity_id


def _contact(state: BranchState, source: uuid.UUID, target: uuid.UUID) -> None:
    unavailable = "party invitation requires nearby participants who can see each other"
    bodies = state.projections.get("tabletop.entities", {})
    positions = state.projections.get("tabletop.spatial.positions", {})
    first, second = bodies.get(str(source), {}), bodies.get(str(target), {})
    if source == target or not capable(first) or not capable(second):
        raise ValueError(unavailable)
    left, right = positions.get(str(source), first), positions.get(str(target), second)
    if (
        (left.get("zone_id", "world"), left.get("z", 0))
        != (right.get("zone_id", "world"), right.get("z", 0))
        or any(axis not in left or axis not in right for axis in ("x", "y"))
        or max(abs(int(left[axis]) - int(right[axis])) for axis in ("x", "y")) > 1
    ):
        raise ValueError(unavailable)
    resolver = GridSpatialPerceptionResolver()
    if target not in resolver.visible_entities(
        state, source
    ) or source not in resolver.visible_entities(state, target):
        raise ValueError(unavailable)


def _set_party(party: Party) -> StateDelta:
    return StateDelta(
        projection=PARTIES,
        operation="SET",
        entity_id=party.party_id,
        values=party.model_dump(mode="json"),
    )


def _set_invitation(invitation: Invitation) -> StateDelta:
    return StateDelta(
        projection=INVITATIONS,
        operation="SET",
        entity_id=invitation.invitation_id,
        values=invitation.model_dump(mode="json"),
    )


def _result(event: PartyEvent, *deltas: StateDelta) -> CommandResult:
    return CommandResult(
        result=event.model_dump(mode="json"),
        deltas=deltas,
        domain_tags=("tabletop", "party", event.kind.lower()),
    )


def create_party(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = CreateParty.model_validate(proposal.parameters)
    founder = _body(proposal)
    if str(founder) not in state.projections.get("tabletop.entities", {}):
        raise ValueError("party action requires a body")
    party = Party(
        **request.model_dump(),
        party_id=stable_event_id(proposal),
        leader_id=founder,
        member_ids=(founder,),
    )
    return _result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=founder,
            kind="CREATED",
            summary="Formed a party around a shared goal.",
        ),
        _set_party(party),
    )


def invite_member(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = InviteMember.model_validate(proposal.parameters)
    inviter = _body(proposal)
    party = _read_party(state, request.party_id)
    if inviter not in party.member_ids or request.invitee_id in party.member_ids:
        raise ValueError("party invitation is unavailable")
    _contact(state, inviter, request.invitee_id)
    pending = [
        row
        for row in state.projections.get(INVITATIONS, {}).values()
        if row["party_id"] == str(party.party_id) and row["status"] == "PENDING"
    ]
    if any(row["invitee_id"] == str(request.invitee_id) for row in pending):
        raise ValueError("party invitation is already pending")
    if len(pending) >= 32:
        raise ValueError("party has too many pending invitations")
    invitation = Invitation(
        party_id=party.party_id,
        invitation_id=stable_event_id(proposal),
        inviter_id=inviter,
        invitee_id=request.invitee_id,
        name=party.name,
        goal=party.goal,
        motive=party.motive,
    )
    return _result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=inviter,
            kind="INVITED",
            invitation_id=invitation.invitation_id,
            invitee_id=invitation.invitee_id,
            summary="Invited someone to join the party.",
        ),
        _set_invitation(invitation),
    )


def respond_to_invitation(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = RespondToInvitation.model_validate(proposal.parameters)
    invitee = _body(proposal)
    raw = state.projections.get(INVITATIONS, {}).get(str(request.invitation_id))
    if raw is None or raw["invitee_id"] != str(invitee) or raw["status"] != "PENDING":
        raise ValueError("party invitation is unavailable")
    invitation = Invitation.model_validate(raw)
    party = _read_party(state, invitation.party_id)
    updated = invitation.model_copy(update={"status": "ACCEPTED" if request.accept else "DECLINED"})
    event_fields = {
        "party_id": party.party_id,
        "actor_entity_id": invitee,
        "invitation_id": invitation.invitation_id,
    }
    if not request.accept:
        return _result(
            PartyEvent(
                **event_fields,
                kind="DECLINED",
                summary="Declined the party invitation.",
            ),
            _set_invitation(updated),
        )
    if invitation.inviter_id not in party.member_ids or invitee in party.member_ids:
        raise ValueError("party invitation is unavailable")
    _contact(state, invitee, invitation.inviter_id)
    updated_party = party.model_copy(update={"member_ids": (*party.member_ids, invitee)})
    prior_departure = party.departure_events.get(invitee)
    return _result(
        PartyEvent(
            **event_fields,
            kind="REUNITED" if prior_departure else "JOINED",
            prior_departure_event_id=prior_departure,
            summary="Rejoined the party." if prior_departure else "Accepted and joined the party.",
        ),
        _set_invitation(updated),
        _set_party(updated_party),
    )


def leave_party(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = LeaveParty.model_validate(proposal.parameters)
    member = _body(proposal)
    party = _read_party(state, request.party_id)
    if member not in party.member_ids:
        raise ValueError("party is unavailable")
    remaining = tuple(identity for identity in party.member_ids if identity != member)
    updated = party.model_copy(
        update={
            "member_ids": remaining,
            "leader_id": party.leader_id
            if party.leader_id != member
            else next(iter(remaining), None),
            "departure_events": {**party.departure_events, member: stable_event_id(proposal)},
        }
    )
    withdrawals = tuple(
        _set_invitation(Invitation.model_validate(row).model_copy(update={"status": "WITHDRAWN"}))
        for _, row in sorted(state.projections.get(INVITATIONS, {}).items())
        if row["party_id"] == str(party.party_id)
        and row["status"] == "PENDING"
        and row["inviter_id"] == str(member)
    )
    return _result(
        PartyEvent(
            party_id=party.party_id,
            actor_entity_id=member,
            kind="HOSTILE_EXIT" if request.hostile else "LEFT",
            reason=request.reason,
            summary="Broke with the party in hostility." if request.hostile else "Left the party.",
        ),
        _set_party(updated),
        *withdrawals,
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    commands: tuple[tuple[str, type[PartyModel], CommandHandler], ...] = (
        ("create", CreateParty, create_party),
        ("invite", InviteMember, invite_member),
        ("respond", RespondToInvitation, respond_to_invitation),
        ("leave", LeaveParty, leave_party),
    )
    return tuple(
        CommandDefinition(
            command_type=f"tabletop.party.{name}",
            version="1.1.0",
            required_capabilities=frozenset({"action.propose", "entity.act"}),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=request,
            result_model=PartyEvent,
            requires_controlled_entity=True,
        )
        for name, request, handler in commands
    )

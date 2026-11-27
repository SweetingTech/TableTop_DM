"""Funded quest contracts; characters cannot author progress, targets or rewards."""

from __future__ import annotations

import uuid

from domains.tabletop.action_time import reserve_counterparty
from domains.tabletop.economy import body, contact, usable_inventory
from domains.tabletop.quests.contracts import (
    QUEST_VERSION,
    QUESTS,
    ConfigureQuest,
    DefeatObjective,
    Evidence,
    Quest,
    QuestReference,
    QuestResult,
    QuestView,
    TradeObjective,
    TransferQuest,
    result,
    view,
)
from domains.tabletop.rules import capable
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.event_factory import stable_event_id
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState


def read(state: BranchState, quest_id: uuid.UUID) -> Quest:
    raw = state.projections.get(QUESTS, {}).get(str(quest_id))
    if raw is None:
        raise ValueError("quest is unavailable")
    return Quest.model_validate(raw)


def set_quest(quest: Quest) -> StateDelta:
    return StateDelta(
        projection=QUESTS,
        operation="SET",
        entity_id=quest.quest_id,
        values=quest.model_dump(mode="json"),
    )


def interaction(
    proposal: CommandProposal, state: BranchState, giver_id: uuid.UUID
) -> tuple[StateDelta, ...]:
    from domains.tabletop.initiative import membership

    owner = proposal.embodied_entity_id
    if owner is None:
        raise ValueError("quest interaction requires a body")
    contact(state, owner, giver_id)
    own, other = membership(state, owner), membership(state, giver_id)
    if other is not None and (own is None or own.encounter_id != other.encounter_id):
        raise ValueError("quest participants must share the giver's encounter")
    timing = reserve_counterparty(proposal, state, giver_id)
    return (timing,) if timing is not None else ()


def quest_contact(
    proposal: CommandProposal, state: BranchState, quest: Quest
) -> tuple[StateDelta, ...]:
    if not quest.alternate_giver_ids:
        return interaction(proposal, state, quest.giver_id)
    for giver in (quest.giver_id, *quest.alternate_giver_ids):
        try:
            return interaction(proposal, state, giver)
        except ValueError:
            continue
    raise ValueError("no authorized quest contact is available nearby")


def check_assignment(state: BranchState, quest: Quest, owner: uuid.UUID) -> None:
    inventory = body(state, owner).get("inventory", {})
    if any(
        int(inventory.get(item, 0)) < quantity for item, quantity in quest.required_items.items()
    ):
        raise ValueError("this body lacks the required items for the task")
    assigned = sum(
        raw.get("owner_id") == str(owner) and raw["status"] in {"ACTIVE", "READY"}
        for raw in state.projections.get(QUESTS, {}).values()
    )
    if assigned >= 16:
        raise ValueError("active personal quest limit reached")


def configure(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = ConfigureQuest.model_validate(proposal.parameters)
    giver = body(state, request.giver_id)
    if not capable(giver):
        raise ValueError("quest giver must be capable")
    active = [
        row
        for row in state.projections.get(QUESTS, {}).values()
        if row["status"] in {"OFFERED", "ACTIVE", "READY"}
    ]
    if len(active) >= 256 or sum(row["giver_id"] == str(request.giver_id) for row in active) >= 16:
        raise ValueError("active quest limit reached")
    contacts = (request.giver_id, *request.alternate_giver_ids)
    if len(set(contacts)) != len(contacts):
        raise ValueError("quest contacts must be distinct bodies")
    for giver_id in request.alternate_giver_ids:
        body(state, giver_id)
    objectives = (
        *request.objectives,
        *(item for approach in request.alternate_approaches for item in approach.objectives),
    )
    for objective in objectives:
        if isinstance(objective, DefeatObjective):
            for identity in objective.target_ids:
                body(state, identity)
        elif isinstance(objective, TradeObjective):
            body(state, objective.counterparty_id)
    if int(giver.get("gold", 0)) < request.reward_gold:
        raise ValueError("giver has insufficient reward funds")
    updates = {"gold": int(giver.get("gold", 0)) - request.reward_gold}
    working = dict(giver)
    for item, quantity in sorted(request.reward_items.items()):
        working.update(usable_inventory(working, item, -quantity))
    if request.reward_items:
        updates.update(
            {key: working[key] for key in ("inventory", "equipped_weapon") if key in working}
        )
    identity = uuid.uuid5(proposal.run_id, f"quest:{proposal.actor_id}:{proposal.idempotency_key}")
    quest = Quest(
        **request.model_dump(),
        quest_id=identity,
        run_id=proposal.run_id,
        source_command_id=proposal.command_id,
        created_sequence=state.version + 1,
        evidence=tuple(Evidence() for _ in request.objectives),
        alternate_evidence=tuple(
            tuple(Evidence() for _ in approach.objectives)
            for approach in request.alternate_approaches
        ),
    )
    return CommandResult(
        result=result(quest, "A task and its reward were offered."),
        deltas=(
            set_quest(quest),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=request.giver_id,
                values=updates,
            ),
        ),
        domain_tags=("operator", "quest_configuration"),
    )


def accept_quest(
    proposal: CommandProposal, state: BranchState, quest: Quest, owner: uuid.UUID
) -> CommandResult:
    previous_owner = (
        quest.owner_id
        if quest.status in {"ACTIVE", "READY"} and quest.transfer_recipient_id == owner
        else None
    )
    if previous_owner is None and quest.status != "OFFERED":
        raise ValueError("quest is no longer offered")
    timing = (
        interaction(proposal, state, previous_owner)
        if previous_owner is not None
        else quest_contact(proposal, state, quest)
    )
    check_assignment(state, quest, owner)
    updated = quest.model_copy(
        update={
            "owner_id": owner,
            "status": quest.status if previous_owner else "ACTIVE",
            "transfer_recipient_id": None,
            "transfer_event_id": None,
        }
    )
    return CommandResult(
        result=result(
            updated,
            "Accepted responsibility for the task."
            if previous_owner
            else "An offered task was accepted.",
            transfer_event_id=quest.transfer_event_id if previous_owner else None,
        ),
        deltas=(set_quest(updated), *timing),
        domain_tags=("tabletop", "quest", "transferred")
        if previous_owner
        else ("tabletop", "quest"),
    )


def reference(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = QuestReference.model_validate(proposal.parameters)
    quest = read(state, request.quest_id)
    owner = proposal.embodied_entity_id
    if owner is None:
        raise ValueError("quest interaction requires a body")
    command = proposal.command_type
    if command == "tabletop.quest.accept":
        return accept_quest(proposal, state, quest, owner)
    if quest.owner_id != owner:
        raise ValueError("quest is not assigned to this body")
    if command == "tabletop.quest.advance":
        return CommandResult(
            result=result(quest, "The task's recorded progress was reviewed."),
            domain_tags=("tabletop", "quest"),
        )
    if quest.status != "READY":
        raise ValueError("quest objectives are not ready for reward")
    timing = quest_contact(proposal, state, quest)
    recipient = dict(body(state, owner))
    for item, quantity in sorted(quest.reward_items.items()):
        recipient.update(usable_inventory(recipient, item, quantity))
    updates = {"gold": int(recipient.get("gold", 0)) + quest.reward_gold}
    if quest.reward_items:
        updates["inventory"] = recipient["inventory"]
    quest = quest.model_copy(
        update={
            "status": "CLAIMED",
            "transfer_recipient_id": None,
            "transfer_event_id": None,
        }
    )
    return CommandResult(
        result=result(quest, "A completed task's promised reward was received."),
        deltas=(
            set_quest(quest),
            StateDelta(
                projection="tabletop.entities", operation="MERGE", entity_id=owner, values=updates
            ),
            *timing,
        ),
        domain_tags=("tabletop", "quest", "reward"),
    )


def offer_transfer(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = TransferQuest.model_validate(proposal.parameters)
    quest = read(state, request.quest_id)
    owner = proposal.embodied_entity_id
    if (
        owner is None
        or quest.owner_id != owner
        or not quest.transferable
        or quest.status not in {"ACTIVE", "READY"}
    ):
        raise ValueError("quest transfer is unavailable")
    timing = interaction(proposal, state, request.recipient_id)
    source = stable_event_id(proposal)
    updated = quest.model_copy(
        update={
            "transfer_recipient_id": request.recipient_id,
            "transfer_event_id": source,
        }
    )
    return CommandResult(
        result=result(
            updated, "Offered to pass on responsibility for the task.", transfer_event_id=source
        ),
        deltas=(set_quest(updated), *timing),
        domain_tags=("tabletop", "quest", "transfer_offer"),
    )


def cancel(proposal: CommandProposal, state: BranchState) -> CommandResult:
    quest = read(state, QuestReference.model_validate(proposal.parameters).quest_id)
    if quest.status in {"CLAIMED", "CANCELLED"}:
        raise ValueError("quest is already settled")
    giver = dict(body(state, quest.giver_id))
    for item, quantity in sorted(quest.reward_items.items()):
        giver.update(usable_inventory(giver, item, quantity))
    updates = {"gold": int(giver.get("gold", 0)) + quest.reward_gold}
    if quest.reward_items:
        updates["inventory"] = giver["inventory"]
    quest = quest.model_copy(
        update={
            "status": "CANCELLED",
            "transfer_recipient_id": None,
            "transfer_event_id": None,
        }
    )
    return CommandResult(
        result=result(quest, "An offered task was withdrawn."),
        deltas=(
            set_quest(quest),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=quest.giver_id,
                values=updates,
            ),
        ),
        domain_tags=("operator", "quest_configuration"),
    )


def visible_quests(
    state: BranchState, observer: uuid.UUID, giver: uuid.UUID
) -> tuple[QuestView, ...]:
    try:
        contact(state, observer, giver)
    except ValueError:
        return ()
    available: list[QuestView] = []
    for _, raw in sorted(state.projections.get(QUESTS, {}).items()):
        if raw["status"] == "OFFERED" and str(giver) in (
            raw["giver_id"],
            *raw.get("alternate_giver_ids", ()),
        ):
            available.append(view(Quest.model_validate(raw)))
        elif (
            raw["status"] in {"ACTIVE", "READY"}
            and raw.get("owner_id") == str(giver)
            and raw.get("transfer_recipient_id") == str(observer)
        ):
            available.append(view(Quest.model_validate(raw), transfer_offer=True))
    return tuple(available)


def personal_quests(state: BranchState, observer: uuid.UUID) -> tuple[QuestView, ...]:
    quests = sorted(
        (
            Quest.model_validate(raw)
            for raw in state.projections.get(QUESTS, {}).values()
            if raw.get("owner_id") == str(observer)
        ),
        key=lambda q: (q.status in {"ACTIVE", "READY"}, q.created_sequence, str(q.quest_id)),
        reverse=True,
    )
    return tuple(view(quest) for quest in quests[:32])


def emission(proposal, result, before, after) -> EventEmission:
    del result, before, after
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="AFTER"),
        modalities=(SensoryModality.SIGHT,),
        max_range=2,
        allowed_payload_fields=("summary",),
        reason_codes=("quest.interaction",),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            command_type=name,
            version=QUEST_VERSION,
            required_capabilities=frozenset(
                {"action.propose", "entity.control" if managed else "entity.act"}
            ),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            handler=handler,
            request_model=model,
            result_model=QuestResult,
            requires_controlled_entity=not managed,
            emission_builder=None if managed else emission,
        )
        for name, handler, model, managed in (
            ("tabletop.quest.configure", configure, ConfigureQuest, True),
            ("tabletop.quest.accept", reference, QuestReference, False),
            ("tabletop.quest.advance", reference, QuestReference, False),
            ("tabletop.quest.claim", reference, QuestReference, False),
            ("tabletop.quest.offer_transfer", offer_transfer, TransferQuest, False),
            ("tabletop.quest.cancel", cancel, QuestReference, True),
        )
    )


def command_definition() -> CommandDefinition:
    return next(d for d in command_definitions() if d.command_type == "tabletop.quest.advance")

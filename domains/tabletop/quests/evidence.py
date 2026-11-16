"""Derive progress only from authorized same-transaction physical outcomes."""

from __future__ import annotations

import uuid

from domains.tabletop.quests import set_quest
from domains.tabletop.quests.contracts import (
    QUESTS,
    DefeatObjective,
    Evidence,
    MoveObjective,
    Objective,
    Quest,
    TradeObjective,
    WorkObjective,
    target,
)
from kernel.command_bus import CommandHandler
from kernel.contracts import CommandProposal, CommandResult
from kernel.state import BranchState

EVIDENCE_COMMANDS = frozenset(
    {
        "tabletop.combat.attack",
        "tabletop.magic.cast",
        "tabletop.magic.invoke",
        "tabletop.spatial.move",
        "tabletop.economy.trade",
        "tabletop.clock.tick",
        "tabletop.clock.advance",
    }
)


def progress(
    objective: Objective,
    old: Evidence,
    owner: uuid.UUID,
    proposal: CommandProposal,
    before: BranchState,
    after: BranchState,
    result: CommandResult,
) -> Evidence:
    bodies, old_bodies = (
        state.projections.get("tabletop.entities", {}) for state in (after, before)
    )
    amount = 0
    seen = set(old.seen_entity_ids)
    own_action = proposal.embodied_entity_id == owner
    if (
        isinstance(objective, DefeatObjective)
        and own_action
        and proposal.command_type
        in {
            "tabletop.combat.attack",
            "tabletop.magic.cast",
            "tabletop.magic.invoke",
        }
    ):
        victim = result.result.get("target_id")
        if victim is not None:
            identity = uuid.UUID(str(victim))
            previous, current = old_bodies.get(str(identity), {}), bodies.get(str(identity), {})
            if (
                identity in objective.target_ids
                and identity not in seen
                and int(previous.get("hp", 0)) > 0
                and int(current.get("hp", 0)) <= 0
            ):
                seen.add(identity)
                amount = 1
    elif (
        isinstance(objective, MoveObjective)
        and own_action
        and proposal.command_type == "tabletop.spatial.move"
    ):
        location = after.projections.get("tabletop.spatial.positions", {}).get(
            str(owner), bodies.get(str(owner), {})
        )
        if (
            location.get("zone_id", "world"),
            int(location.get("x", 0)),
            int(location.get("y", 0)),
            int(location.get("z", 0)),
        ) == (
            objective.zone_id,
            objective.x,
            objective.y,
            objective.z,
        ):
            amount = 1
    elif isinstance(objective, WorkObjective) and proposal.command_type in {
        "tabletop.clock.tick",
        "tabletop.clock.advance",
    }:
        amount = max(
            0,
            int(bodies.get(str(owner), {}).get("weeded_units", 0))
            - int(old_bodies.get(str(owner), {}).get("weeded_units", 0)),
        )
    elif (
        isinstance(objective, TradeObjective)
        and own_action
        and proposal.command_type == "tabletop.economy.trade"
    ):
        own_key, other_key = (
            ("buyer_id", "seller_id") if objective.side == "BUY" else ("seller_id", "buyer_id")
        )
        outcome = result.result
        if (
            outcome.get(own_key) == str(owner)
            and outcome.get(other_key) == str(objective.counterparty_id)
            and outcome.get("item") == objective.item
        ):
            amount = int(outcome["quantity"])
    value = min(target(objective), old.progress + amount)
    if value == old.progress:
        return old
    return Evidence(
        progress=value,
        seen_entity_ids=tuple(sorted(seen, key=str)),
        last_source_command_id=proposal.command_id,
    )


def with_quest_evidence(handler: CommandHandler) -> CommandHandler:
    def execute(proposal: CommandProposal, state: BranchState) -> CommandResult:
        result = handler(proposal, state)
        if not result.accepted or proposal.command_type not in EVIDENCE_COMMANDS:
            return result
        after = state.working_copy()
        for delta in result.deltas:
            after.apply(delta)
        deltas = []
        for _, raw in sorted(state.projections.get(QUESTS, {}).items()):
            quest = Quest.model_validate(raw)
            if quest.status != "ACTIVE" or quest.owner_id is None:
                continue
            evidence = tuple(
                progress(o, e, quest.owner_id, proposal, state, after, result)
                for o, e in zip(quest.objectives, quest.evidence, strict=True)
            )
            if evidence == quest.evidence:
                continue
            ready = all(
                e.progress >= target(o) for o, e in zip(quest.objectives, evidence, strict=True)
            )
            deltas.append(
                set_quest(
                    quest.model_copy(
                        update={"evidence": evidence, "status": "READY" if ready else "ACTIVE"}
                    )
                )
            )
        return result.model_copy(update={"deltas": (*result.deltas, *deltas)})

    return execute

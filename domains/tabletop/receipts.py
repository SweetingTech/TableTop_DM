"""Public receipt presentation; internal projection deltas remain replay evidence."""

from __future__ import annotations

from typing import Any

from kernel.contracts import CommandResult

PRIVATE_PROJECTIONS = frozenset(
    {
        "tabletop.quest_contracts",
        "tabletop.trade_offers",
        "tabletop.parties",
        "tabletop.party_invitations",
    }
)


def present_command_result(result: CommandResult, *, include_private: bool) -> dict[str, Any]:
    if include_private:
        return result.model_dump(mode="json")
    private = {
        index
        for index, delta in enumerate(result.deltas)
        if delta.projection in PRIVATE_PROJECTIONS
    }
    return result.model_dump(mode="json", exclude={"deltas": private})

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.state import BranchState


class TradeRequest(BaseModel):
    counterparty_id: uuid.UUID
    item: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=100_000)
    unit_price: int = Field(ge=0, le=1_000_000)
    direction: Literal["BUY", "SELL"]


class TradeResult(BaseModel):
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    item: str
    quantity: int = Field(ge=1)
    price: int = Field(ge=0)


def trade(proposal: CommandProposal, state: BranchState) -> CommandResult:
    actor_entity_id = proposal.embodied_entity_id
    if actor_entity_id is None:
        raise ValueError("trade requires an embodied entity")
    request = TradeRequest.model_validate(proposal.parameters)
    entities = state.projections.get("tabletop.entities", {})
    actor_entity = entities.get(str(actor_entity_id))
    counterparty = entities.get(str(request.counterparty_id))
    if actor_entity is None or counterparty is None:
        raise ValueError("both trade parties must exist")
    buyer_id, seller_id = (
        (actor_entity_id, request.counterparty_id)
        if request.direction == "BUY"
        else (request.counterparty_id, actor_entity_id)
    )
    buyer = entities[str(buyer_id)]
    seller = entities[str(seller_id)]
    price = request.quantity * request.unit_price
    buyer_inventory = dict(buyer.get("inventory", {}))
    seller_inventory = dict(seller.get("inventory", {}))
    if int(buyer.get("gold", 0)) < price:
        raise ValueError("buyer has insufficient gold")
    if int(seller_inventory.get(request.item, 0)) < request.quantity:
        raise ValueError("seller has insufficient inventory")
    buyer_inventory[request.item] = int(buyer_inventory.get(request.item, 0)) + request.quantity
    seller_inventory[request.item] = int(seller_inventory[request.item]) - request.quantity
    return CommandResult(
        result={
            "buyer_id": str(buyer_id),
            "seller_id": str(seller_id),
            "item": request.item,
            "quantity": request.quantity,
            "price": price,
        },
        deltas=(
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=buyer_id,
                values={"gold": int(buyer.get("gold", 0)) - price, "inventory": buyer_inventory},
            ),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=seller_id,
                values={"gold": int(seller.get("gold", 0)) + price, "inventory": seller_inventory},
            ),
        ),
        domain_tags=("tabletop", "economy", "trade"),
    )


def command_definition() -> CommandDefinition:
    return CommandDefinition(
        command_type="tabletop.economy.trade",
        required_capabilities=frozenset({"action.propose", "entity.act"}),
        allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
        handler=trade,
        request_model=TradeRequest,
        result_model=TradeResult,
        requires_controlled_entity=True,
    )

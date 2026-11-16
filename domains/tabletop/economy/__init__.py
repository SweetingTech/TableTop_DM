"""Consensual contact trades over canonical carried escrow, never taker-selected prices."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from domains.tabletop.action_time import reserve_counterparty
from domains.tabletop.rules import capable
from domains.tabletop.spatial.perception import GridSpatialPerceptionResolver
from kernel.command_bus import CommandDefinition
from kernel.contracts import BranchKind, CommandProposal, CommandResult, StateDelta
from kernel.perception_contracts import EventEmission, SensoryModality, SpatialAnchor
from kernel.state import BranchState

OFFERS = "tabletop.trade_offers"
TRADE_VERSION = "tabletop-trade-2.0.0"


class OfferIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    side: Literal["SELL", "BUY"]
    item: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9 _-]*$")
    quantity: int = Field(ge=1, le=100000)
    unit_price: int = Field(ge=0, le=1000000)
    valid_for_seconds: int = Field(default=86400, ge=1, le=86400)


class ConfigureOffer(OfferIntent):
    maker_id: uuid.UUID


class Offer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    offer_id: uuid.UUID
    maker_id: uuid.UUID
    run_id: uuid.UUID
    source_command_id: uuid.UUID
    rules_version: str = TRADE_VERSION
    side: Literal["SELL", "BUY"]
    item: str
    remaining_quantity: int = Field(ge=1, le=100000)
    unit_price: int = Field(ge=0, le=1000000)
    valid_for_seconds: int = Field(ge=1, le=86400)
    created_seconds: int | None = Field(default=None, ge=0)
    expires_seconds: int | None = Field(default=None, ge=0)


class OfferResult(BaseModel):
    offer_id: uuid.UUID
    maker_id: uuid.UUID
    side: Literal["SELL", "BUY"]
    item: str
    remaining_quantity: int
    unit_price: int
    summary: str


class OfferReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: uuid.UUID


class TradeRequest(OfferReference):
    quantity: int = Field(default=1, ge=1, le=100000)


class TradeResult(BaseModel):
    offer_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    item: str
    quantity: int = Field(ge=1)
    price: int = Field(ge=0)
    summary: str


def now(state: BranchState, run_id: uuid.UUID) -> int | None:
    clock = state.projections.get("tabletop.clock", {}).get("singleton")
    if clock is None:
        return None
    if str(clock["run_id"]) != str(run_id):
        raise ValueError("trade requires the current run's clock")
    return int(clock["seconds"])


def body(state: BranchState, entity_id: uuid.UUID) -> dict:
    value = state.projections.get("tabletop.entities", {}).get(str(entity_id))
    if value is None:
        raise ValueError("trade body is unavailable")
    return value


def usable_inventory(values: dict, item: str, delta: int) -> dict:
    inventory = dict(values.get("inventory", {}))
    quantity = int(inventory.get(item, 0)) + delta
    if quantity < 0:
        raise ValueError("insufficient inventory")
    inventory[item] = quantity
    updates: dict = {"inventory": dict(sorted(inventory.items()))}
    if str(values.get("equipped_weapon", "UNARMED")) == item and quantity == 0:
        updates["equipped_weapon"] = "UNARMED"
    return updates


def offer_result(row: Offer, summary: str) -> dict:
    return OfferResult(
        offer_id=row.offer_id,
        maker_id=row.maker_id,
        side=row.side,
        item=row.item,
        remaining_quantity=row.remaining_quantity,
        unit_price=row.unit_price,
        summary=summary,
    ).model_dump(mode="json")


def create(proposal: CommandProposal, state: BranchState) -> CommandResult:
    managed = proposal.command_type == "tabletop.economy.configure_offer"
    request = (ConfigureOffer if managed else OfferIntent).model_validate(proposal.parameters)
    maker_id = (
        request.maker_id if isinstance(request, ConfigureOffer) else proposal.embodied_entity_id
    )
    if maker_id is None:
        raise ValueError("offer requires a maker")
    maker = body(state, maker_id)
    if not capable(maker):
        raise ValueError("offer requires a capable maker")
    rows = state.projections.get(OFFERS, {})
    if len(rows) >= 256 or sum(raw["maker_id"] == str(maker_id) for raw in rows.values()) >= 16:
        raise ValueError("active trade offer limit reached")
    at = now(state, proposal.run_id)
    if request.side == "SELL":
        resources = usable_inventory(maker, request.item, -request.quantity)
    else:
        price = request.quantity * request.unit_price
        if int(maker.get("gold", 0)) < price:
            raise ValueError("insufficient offer funds")
        resources = {"gold": int(maker.get("gold", 0)) - price}
    identity = uuid.uuid5(
        proposal.run_id, f"trade-offer:{proposal.actor_id}:{proposal.idempotency_key}"
    )
    row = Offer(
        offer_id=identity,
        maker_id=maker_id,
        run_id=proposal.run_id,
        source_command_id=proposal.command_id,
        side=request.side,
        item=request.item,
        remaining_quantity=request.quantity,
        unit_price=request.unit_price,
        valid_for_seconds=request.valid_for_seconds,
        created_seconds=at,
        expires_seconds=at + request.valid_for_seconds if at is not None else None,
    )
    return CommandResult(
        result=offer_result(row, f"An offer to {row.side.lower()} {row.item} was made."),
        deltas=(
            StateDelta(
                projection=OFFERS,
                operation="SET",
                entity_id=identity,
                values=row.model_dump(mode="json"),
            ),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=maker_id,
                values=resources,
            ),
        ),
        domain_tags=("operator", "trade_configuration") if managed else ("tabletop", "trade_offer"),
    )


def read_offer(state: BranchState, offer_id: uuid.UUID, *, at: int | None = None) -> Offer:
    raw = state.projections.get(OFFERS, {}).get(str(offer_id))
    if raw is None:
        raise ValueError("trade offer is unavailable")
    row = Offer.model_validate(raw)
    if at is not None and row.expires_seconds is not None and at >= row.expires_seconds:
        raise ValueError("trade offer expired")
    return row


def contact(state: BranchState, taker_id: uuid.UUID, maker_id: uuid.UUID) -> None:
    if taker_id == maker_id:
        raise ValueError("a body cannot trade with its own offer")
    taker, maker = body(state, taker_id), body(state, maker_id)
    if not capable(taker) or not capable(maker):
        raise ValueError("trade requires capable participants")
    positions = state.projections.get("tabletop.spatial.positions", {})
    left, right = positions.get(str(taker_id), taker), positions.get(str(maker_id), maker)
    if (left.get("zone_id", "world"), left.get("z", 0)) != (
        right.get("zone_id", "world"),
        right.get("z", 0),
    ):
        raise ValueError("trade requires the same physical place")
    if max(abs(int(left.get(axis, 0)) - int(right.get(axis, 0))) for axis in ("x", "y")) > 1:
        raise ValueError("trade requires adjacent participants")
    if maker_id not in GridSpatialPerceptionResolver().visible_entities(state, taker_id):
        raise ValueError("trade requires a perceived counterparty")


def trade(proposal: CommandProposal, state: BranchState) -> CommandResult:
    taker_id = proposal.embodied_entity_id
    if taker_id is None:
        raise ValueError("trade requires an embodied entity")
    request = TradeRequest.model_validate(proposal.parameters)
    row = read_offer(state, request.offer_id, at=now(state, proposal.run_id))
    contact(state, taker_id, row.maker_id)
    if request.quantity > row.remaining_quantity:
        raise ValueError("offer has insufficient remaining quantity")
    timing = reserve_counterparty(proposal, state, row.maker_id)
    from domains.tabletop.initiative import membership

    own, other = membership(state, taker_id), membership(state, row.maker_id)
    if other is not None and (own is None or own.encounter_id != other.encounter_id):
        raise ValueError("participants must share the counterparty's encounter")
    taker, maker = body(state, taker_id), body(state, row.maker_id)
    price = request.quantity * row.unit_price
    if row.side == "SELL":
        if int(taker.get("gold", 0)) < price:
            raise ValueError("buyer has insufficient gold")
        taker_updates = {
            **usable_inventory(taker, row.item, request.quantity),
            "gold": int(taker.get("gold", 0)) - price,
        }
        maker_updates = {"gold": int(maker.get("gold", 0)) + price}
        buyer_id, seller_id = taker_id, row.maker_id
    else:
        taker_updates = {
            **usable_inventory(taker, row.item, -request.quantity),
            "gold": int(taker.get("gold", 0)) + price,
        }
        maker_updates = usable_inventory(maker, row.item, request.quantity)
        buyer_id, seller_id = row.maker_id, taker_id
    remaining = row.remaining_quantity - request.quantity
    deltas = [
        StateDelta(
            projection="tabletop.entities",
            operation="MERGE",
            entity_id=taker_id,
            values=taker_updates,
        ),
        StateDelta(
            projection="tabletop.entities",
            operation="MERGE",
            entity_id=row.maker_id,
            values=maker_updates,
        ),
        StateDelta(
            projection=OFFERS,
            operation="MERGE" if remaining else "DELETE",
            entity_id=row.offer_id,
            values={"remaining_quantity": remaining} if remaining else {},
        ),
    ]
    if timing is not None:
        deltas.append(timing)
    return CommandResult(
        result=TradeResult(
            offer_id=row.offer_id,
            buyer_id=buyer_id,
            seller_id=seller_id,
            item=row.item,
            quantity=request.quantity,
            price=price,
            summary=f"A trade of {request.quantity} {row.item} for {price} gold was completed.",
        ).model_dump(mode="json"),
        deltas=tuple(deltas),
        domain_tags=("tabletop", "economy", "trade"),
    )


def refund(state: BranchState, row: Offer) -> dict:
    maker = body(state, row.maker_id)
    return (
        usable_inventory(maker, row.item, row.remaining_quantity)
        if row.side == "SELL"
        else {"gold": int(maker.get("gold", 0)) + row.unit_price * row.remaining_quantity}
    )


def cancel(proposal: CommandProposal, state: BranchState) -> CommandResult:
    request = OfferReference.model_validate(proposal.parameters)
    row = read_offer(state, request.offer_id)
    now(state, proposal.run_id)
    managed = proposal.command_type == "tabletop.economy.cancel_offer"
    if not managed and row.maker_id != proposal.embodied_entity_id:
        raise ValueError("only the offer maker can withdraw it")
    return CommandResult(
        result=offer_result(row, "A trade offer was withdrawn."),
        deltas=(
            StateDelta(projection=OFFERS, operation="DELETE", entity_id=row.offer_id),
            StateDelta(
                projection="tabletop.entities",
                operation="MERGE",
                entity_id=row.maker_id,
                values=refund(state, row),
            ),
        ),
        domain_tags=("operator", "trade_configuration") if managed else ("tabletop", "trade_offer"),
    )


def boundaries(state: BranchState, start: int, until: int) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                int(row["expires_seconds"])
                for row in state.projections.get(OFFERS, {}).values()
                if row.get("expires_seconds") is not None
                and start < int(row["expires_seconds"]) <= until
            }
        )
    )


def expire(state: BranchState, at: int) -> None:
    """Only the clock handler's private working copy may enter this function."""
    rows = state.projections.get(OFFERS, {})
    for identity, raw in sorted(tuple(rows.items())):
        row = Offer.model_validate(raw)
        if row.expires_seconds is None:
            row = row.model_copy(
                update={"created_seconds": at, "expires_seconds": at + row.valid_for_seconds}
            )
            rows[identity] = row.model_dump(mode="json")
        if row.expires_seconds is not None and row.expires_seconds <= at:
            body(state, row.maker_id).update(refund(state, row))
            del rows[identity]


def visible_offers(
    state: BranchState, observer_id: uuid.UUID, maker_id: uuid.UUID
) -> tuple[dict, ...]:
    try:
        if observer_id != maker_id:
            contact(state, observer_id, maker_id)
    except ValueError:
        return ()
    clock = state.projections.get("tabletop.clock", {}).get("singleton", {})
    at = int(clock.get("seconds", 0))
    return tuple(
        {
            "offer_id": row.offer_id,
            "side": row.side,
            "item": row.item,
            "quantity": row.remaining_quantity,
            "unit_price": row.unit_price,
        }
        for _, raw in sorted(state.projections.get(OFFERS, {}).items())
        if (row := Offer.model_validate(raw)).maker_id == maker_id
        and (row.expires_seconds is None or row.expires_seconds > at)
    )


def trade_emission(proposal, result, before, after) -> EventEmission:
    del result, before, after
    return EventEmission(
        anchor=SpatialAnchor(entity_id=proposal.embodied_entity_id, phase="AFTER"),
        modalities=(SensoryModality.SIGHT,),
        max_range=2,
        allowed_payload_fields=("summary", "item", "quantity", "price"),
        reason_codes=("trade.exchange",),
    )


def command_definitions() -> tuple[CommandDefinition, ...]:
    return tuple(
        CommandDefinition(
            command_type=name,
            version=TRADE_VERSION,
            required_capabilities=frozenset(
                {"action.propose", "entity.control" if managed else "entity.act"}
            ),
            allowed_branch_kinds=frozenset({BranchKind.CANONICAL, BranchKind.TRIAL}),
            requires_controlled_entity=not managed,
            handler=handler,
            request_model=model,
            result_model=TradeResult if name == "tabletop.economy.trade" else OfferResult,
            emission_builder=None if managed else trade_emission,
        )
        for name, handler, model, managed in (
            ("tabletop.economy.trade", trade, TradeRequest, False),
            ("tabletop.economy.offer", create, OfferIntent, False),
            ("tabletop.economy.configure_offer", create, ConfigureOffer, True),
            ("tabletop.economy.withdraw_offer", cancel, OfferReference, False),
            ("tabletop.economy.cancel_offer", cancel, OfferReference, True),
        )
    )


def command_definition() -> CommandDefinition:
    return command_definitions()[0]

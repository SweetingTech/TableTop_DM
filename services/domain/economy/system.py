import uuid
from shared.db.connection import execute_query, execute_one, get_connection
from shared.schemas.events import StateDelta


class EconomySystem:
    def get_location_metrics(self, location_entity_id: uuid.UUID) -> dict:
        row = execute_one(
            "SELECT * FROM state.location_metrics WHERE location_entity_id = %s",
            (str(location_entity_id),),
        )
        if not row:
            return {"stability": 100, "scarcity_index": 1.0, "prosperity_index": 1.0}
        return dict(row)

    def update_location_metrics(
        self,
        location_entity_id: uuid.UUID,
        stability_delta: int = 0,
        scarcity_delta: float = 0,
        prosperity_delta: float = 0,
        conn=None,
    ) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state.location_metrics (location_entity_id, stability, scarcity_index, prosperity_index)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (location_entity_id) DO UPDATE SET
                    stability = GREATEST(0, LEAST(100, state.location_metrics.stability + %s)),
                    scarcity_index = GREATEST(0.1, LEAST(10.0, state.location_metrics.scarcity_index + %s)),
                    prosperity_index = GREATEST(0.1, LEAST(10.0, state.location_metrics.prosperity_index + %s))
            """,
                (
                    str(location_entity_id),
                    max(0, min(100, 100 + stability_delta)),
                    max(0.1, min(10.0, 1.0 + scarcity_delta)),
                    max(0.1, min(10.0, 1.0 + prosperity_delta)),
                    stability_delta,
                    scarcity_delta,
                    prosperity_delta,
                ),
            )

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def compute_item_price(
        self, shop_id: uuid.UUID, item_entity_id: uuid.UUID, campaign_id: uuid.UUID
    ) -> dict:
        shop = execute_one("SELECT * FROM state.shops WHERE id = %s", (str(shop_id),))
        if not shop:
            return {"error": "Shop not found"}

        item = execute_one(
            "SELECT * FROM state.shop_inventory WHERE shop_id = %s AND item_entity_id = %s",
            (str(shop_id), str(item_entity_id)),
        )
        if not item:
            return {"error": "Item not in shop"}

        base_price = float(item["base_price"])
        shop_multiplier = float(shop["price_multiplier"])

        metrics = self.get_location_metrics(shop["location_entity_id"])
        scarcity = float(metrics.get("scarcity_index", 1.0))
        stability = metrics.get("stability", 100)

        stability_mult = 1.0 + (100 - stability) / 200.0

        modifiers = execute_query(
            """
            SELECT modifier FROM state.price_modifiers
            WHERE campaign_id = %s AND (
                (scope_type = 'SHOP' AND scope_id = %s) OR
                (scope_type = 'LOCATION' AND scope_id = %s) OR
                scope_type = 'GLOBAL'
            )
        """,
            (str(campaign_id), str(shop_id), str(shop["location_entity_id"])),
        )

        extra_mult = 1.0
        for m in modifiers:
            extra_mult *= float(m["modifier"])

        final_price = (
            base_price * shop_multiplier * scarcity * stability_mult * extra_mult
        )
        final_price = round(max(0.01, final_price), 2)

        return {
            "item_entity_id": str(item_entity_id),
            "base_price": base_price,
            "shop_multiplier": shop_multiplier,
            "scarcity_multiplier": scarcity,
            "stability_multiplier": round(stability_mult, 3),
            "extra_multiplier": round(extra_mult, 3),
            "final_price": final_price,
            "quantity_available": item["quantity"],
        }


class PropertySystem:
    def buy_property(
        self,
        property_entity_id: uuid.UUID,
        buyer_entity_id: uuid.UUID,
        upkeep_cost: float,
        conn=None,
    ) -> dict:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state.property_ownership (property_entity_id, owner_entity_id, acquired_at, upkeep_cost)
                VALUES (%s, %s, now(), %s)
                ON CONFLICT (property_entity_id) DO UPDATE SET
                    owner_entity_id = EXCLUDED.owner_entity_id,
                    acquired_at = now(),
                    upkeep_cost = EXCLUDED.upkeep_cost
            """,
                (str(property_entity_id), str(buyer_entity_id), upkeep_cost),
            )

            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "property_id": str(property_entity_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def process_upkeep(self, campaign_id: uuid.UUID, conn=None) -> list[StateDelta]:
        properties = execute_query(
            """
            SELECT po.*, e.name as property_name
            FROM state.property_ownership po
            JOIN state.entities e ON po.property_entity_id = e.id
            WHERE e.campaign_id = %s
        """,
            (str(campaign_id),),
        )

        deltas = []
        for prop in properties:
            deltas.append(
                StateDelta(
                    table="state.property_ownership",
                    operation="UPDATE",
                    entity_id=prop["property_entity_id"],
                    changes={
                        "upkeep_charged": float(prop["upkeep_cost"]),
                        "owner_entity_id": str(prop["owner_entity_id"]),
                    },
                    domain_tags=["economy", "upkeep"],
                )
            )

        return deltas

    def compute_raid_risk(self, property_entity_id: uuid.UUID) -> dict:
        prop = execute_one(
            """
            SELECT po.*, e.campaign_id
            FROM state.property_ownership po
            JOIN state.entities e ON po.property_entity_id = e.id
            WHERE po.property_entity_id = %s
        """,
            (str(property_entity_id),),
        )

        if not prop:
            return {"risk": 0.0}

        from services.domain.economy.system import EconomySystem

        eco = EconomySystem()
        location = execute_one(
            """
            SELECT id FROM state.entities
            WHERE campaign_id = %s AND entity_type = 'LOCATION'
            LIMIT 1
        """,
            (str(prop["campaign_id"]),),
        )

        if location:
            metrics = eco.get_location_metrics(location["id"])
            stability = metrics.get("stability", 100)
            risk = max(0.0, (100 - stability) / 100.0)
        else:
            risk = 0.1

        return {
            "property_id": str(property_entity_id),
            "raid_risk": round(risk, 3),
        }

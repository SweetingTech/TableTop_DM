import uuid
from shared.schemas.enums import GameMode, VALID_MODE_TRANSITIONS, EncounterStatus
from shared.db.connection import execute_one, execute_query


class StateMachine:

    def get_campaign_mode(self, campaign_id: uuid.UUID) -> GameMode:
        row = execute_one(
            "SELECT mode FROM state.campaigns WHERE id = %s",
            (str(campaign_id),)
        )
        if not row:
            raise ValueError(f"Campaign {campaign_id} not found")
        return GameMode(row["mode"])

    def set_campaign_mode(self, campaign_id: uuid.UUID, new_mode: GameMode, conn=None) -> dict:
        current = self.get_campaign_mode(campaign_id)
        if new_mode not in VALID_MODE_TRANSITIONS.get(current, set()):
            return {
                "success": False,
                "reason": f"Cannot transition from {current.value} to {new_mode.value}",
            }

        from shared.db.connection import get_connection
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE state.campaigns SET mode = %s, updated_at = now() WHERE id = %s",
                (new_mode.value, str(campaign_id))
            )
            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "previous_mode": current.value, "new_mode": new_mode.value}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def get_active_encounter(self, campaign_id: uuid.UUID) -> dict | None:
        row = execute_one(
            "SELECT * FROM state.encounters WHERE campaign_id = %s AND status = 'ACTIVE' LIMIT 1",
            (str(campaign_id),)
        )
        return dict(row) if row else None

    def get_encounter_slots(self, encounter_id: uuid.UUID) -> list[dict]:
        rows = execute_query("""
            SELECT es.*, e.name as entity_name, e.hp_current, e.hp_max, e.ac,
                   e.speed, e.controlled_by, e.controller_principal_id
            FROM state.encounter_slots es
            JOIN state.entities e ON es.entity_id = e.id
            WHERE es.encounter_id = %s
            ORDER BY es.turn_order ASC
        """, (str(encounter_id),))
        return [dict(r) for r in rows]

    def get_active_slot(self, encounter_id: uuid.UUID) -> dict | None:
        row = execute_one("""
            SELECT es.*, e.name as entity_name, e.controlled_by,
                   e.controller_principal_id
            FROM state.encounter_slots es
            JOIN state.entities e ON es.entity_id = e.id
            WHERE es.encounter_id = %s AND es.is_active = true
            LIMIT 1
        """, (str(encounter_id),))
        return dict(row) if row else None

    def advance_turn(self, encounter_id: uuid.UUID, conn=None) -> dict:
        from shared.db.connection import get_connection
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()

            import psycopg2.extras
            dict_cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            dict_cur.execute("""
                SELECT es.id, es.turn_order, es.entity_id, e.name
                FROM state.encounter_slots es
                JOIN state.entities e ON es.entity_id = e.id
                WHERE es.encounter_id = %s
                ORDER BY es.turn_order ASC
            """, (str(encounter_id),))
            slots = dict_cur.fetchall()

            dict_cur.execute(
                "SELECT id, turn_order FROM state.encounter_slots WHERE encounter_id = %s AND is_active = true",
                (str(encounter_id),)
            )
            active = dict_cur.fetchone()

            if not active or not slots:
                dict_cur.close()
                cur.close()
                if own_conn:
                    conn.close()
                return {"success": False, "reason": "No active slot or slots"}

            current_order = active["turn_order"]
            next_slot = None
            new_round = False

            for s in slots:
                if s["turn_order"] > current_order:
                    next_slot = s
                    break

            if next_slot is None:
                next_slot = slots[0]
                new_round = True

            cur.execute(
                "UPDATE state.encounter_slots SET is_active = false WHERE encounter_id = %s",
                (str(encounter_id),)
            )
            cur.execute(
                "UPDATE state.encounter_slots SET is_active = true WHERE id = %s",
                (str(next_slot["id"]),)
            )
            cur.execute(
                "UPDATE state.encounters SET active_slot = %s WHERE id = %s",
                (next_slot["turn_order"], str(encounter_id))
            )

            if new_round:
                cur.execute(
                    "UPDATE state.encounters SET round_number = round_number + 1 WHERE id = %s",
                    (str(encounter_id),)
                )

            if own_conn:
                conn.commit()
            dict_cur.close()
            cur.close()

            return {
                "success": True,
                "new_round": new_round,
                "active_entity_id": str(next_slot["entity_id"]),
                "active_entity_name": next_slot["name"],
                "turn_order": next_slot["turn_order"],
            }
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

    def end_encounter(self, encounter_id: uuid.UUID, conn=None) -> dict:
        from shared.db.connection import get_connection
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE state.encounters SET status = %s, updated_at = now() WHERE id = %s",
                (EncounterStatus.COMPLETED.value, str(encounter_id))
            )
            if own_conn:
                conn.commit()
            cur.close()
            return {"success": True, "encounter_id": str(encounter_id)}
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

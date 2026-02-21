import uuid
from typing import Optional
from shared.db.connection import execute_query, get_connection
from shared.schemas.events import StateDelta


DOMAIN_TAG_WEIGHTS = {
    "damage": {"violence": 1, "destruction": 1},
    "healing": {"mercy": 1, "life": 1},
    "combat": {"violence": 1, "war": 1},
    "theft": {"trickery": 2, "greed": 1},
    "murder": {"death": 3, "violence": 2, "evil": 2},
    "charity": {"mercy": 2, "life": 1, "good": 1},
    "deception": {"trickery": 2},
    "justice": {"order": 2, "good": 1},
    "nature": {"nature": 2, "life": 1},
    "undead": {"death": 2, "evil": 1},
    "divine": {"divine": 1},
    "arcane": {"knowledge": 1, "arcane": 1},
    "protection": {"protection": 2, "good": 1},
    "destruction": {"destruction": 2, "chaos": 1},
    "chaos": {"chaos": 2},
    "order": {"order": 2},
}

STANDING_THRESHOLDS = [-50, -25, -10, 10, 25, 50]


class KarmaRouter:
    def process_domain_tags(
        self, campaign_id: uuid.UUID, entity_id: uuid.UUID, domain_tags: list[str]
    ) -> list[dict]:
        standings_changes = []

        gods = execute_query(
            """
            SELECT e.id, e.name, e.public_sheet, ds.standing
            FROM state.entities e
            LEFT JOIN state.divine_standings ds ON ds.god_entity_id = e.id AND ds.entity_id = %s
            WHERE e.campaign_id = %s AND e.entity_type = 'GOD'
        """,
            (str(entity_id), str(campaign_id)),
        )

        if not gods:
            gods = execute_query(
                """
                SELECT e.id, e.name, e.public_sheet
                FROM state.entities e
                WHERE e.campaign_id = %s AND e.controlled_by = 'AI_GOD'
            """,
                (str(campaign_id),),
            )

        for god in gods:
            god_sheet = god.get("public_sheet", {})
            god_domains = god_sheet.get("domains", [])
            current_standing = god.get("standing", 0) or 0
            delta = 0

            for tag in domain_tags:
                weights = DOMAIN_TAG_WEIGHTS.get(tag, {})
                for domain, weight in weights.items():
                    if domain in god_domains:
                        delta += weight
                    elif domain in ("evil", "chaos") and "good" in god_domains:
                        delta -= weight
                    elif domain in ("good", "order") and "evil" in god_domains:
                        delta -= weight

            if delta != 0:
                new_standing = current_standing + delta
                standings_changes.append(
                    {
                        "god_id": str(god["id"]),
                        "god_name": god["name"],
                        "entity_id": str(entity_id),
                        "previous_standing": current_standing,
                        "new_standing": new_standing,
                        "delta": delta,
                        "threshold_crossed": self._check_threshold(
                            current_standing, new_standing
                        ),
                    }
                )

        return standings_changes

    def _check_threshold(self, old: int, new: int) -> Optional[int]:
        for t in STANDING_THRESHOLDS:
            if (old < t <= new) or (old > t >= new):
                return t
        return None

    def apply_standing_changes(
        self, changes: list[dict], campaign_id: uuid.UUID, conn=None
    ) -> list[StateDelta]:
        own_conn = conn is None
        if own_conn:
            conn = get_connection()

        deltas = []
        try:
            cur = conn.cursor()
            for change in changes:
                cur.execute(
                    """
                    INSERT INTO state.divine_standings (god_entity_id, entity_id, standing, campaign_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (god_entity_id, entity_id) DO UPDATE
                    SET standing = EXCLUDED.standing
                """,
                    (
                        change["god_id"],
                        change["entity_id"],
                        change["new_standing"],
                        str(campaign_id),
                    ),
                )

                deltas.append(
                    StateDelta(
                        table="state.divine_standings",
                        operation="UPSERT",
                        entity_id=uuid.UUID(change["entity_id"]),
                        changes={
                            "god_id": change["god_id"],
                            "previous_standing": change["previous_standing"],
                            "new_standing": change["new_standing"],
                        },
                        domain_tags=["karma", "standing_change"],
                    )
                )

            if own_conn:
                conn.commit()
            cur.close()
        except Exception:
            if own_conn:
                conn.rollback()
            raise
        finally:
            if own_conn:
                conn.close()

        return deltas

    def get_threshold_wakes(self, changes: list[dict]) -> list[dict]:
        return [c for c in changes if c.get("threshold_crossed") is not None]

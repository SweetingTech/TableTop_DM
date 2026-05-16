"""Game save = everything tied to one campaign.

Export collects every row that belongs to a campaign across all the tables
the cascade-purge touches (in reverse — purge order tells us exactly what
dependencies exist).

Import re-creates everything with the IDs from the file. If a campaign with
the same id already exists, the importer refuses unless `replace=True` is
passed, in which case it cascade-purges the old one first.

Principal references are migrated by `auth_subject` rather than UUID so a
game saved on one machine plays on another (each install has its own
LocalPlayer principal_id, but they share auth_subject='local:player').
"""

import json
import uuid
from typing import Optional

from shared.db.connection import get_connection, execute_one, execute_query


# ------------------------------------------------------------------------
# Export
# ------------------------------------------------------------------------

def _rows(table: str, where: str, params: tuple) -> list[dict]:
    """Run a SELECT and return JSON-safe dicts. UUIDs become strings, etc."""
    rows = execute_query(f"SELECT * FROM {table} WHERE {where}", params)
    out = []
    for r in rows:
        out.append({k: _jsonify(v) for k, v in r.items()})
    return out


def _jsonify(v):
    """Coerce DB values into JSON-safe shapes."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):  # datetime, date
        return v.isoformat()
    if isinstance(v, (dict, list, str, int, float, bool)):
        return v
    return str(v)


def export_campaign(campaign_id: uuid.UUID) -> dict:
    """Return a portable dict representing the entire campaign."""
    cid = (str(campaign_id),)

    campaign = execute_one("SELECT * FROM state.campaigns WHERE id = %s", cid)
    if not campaign:
        raise ValueError(f"Campaign {campaign_id} not found")

    # Members: include the principal's auth_subject + display_name + type so
    # the importer can find or recreate the right principal on the destination.
    members = execute_query(
        """
        SELECT m.role, p.auth_subject, p.display_name, p.principal_type, p.id AS principal_id
        FROM state.campaign_members m
        JOIN state.principals p ON p.id = m.principal_id
        WHERE m.campaign_id = %s
        """,
        cid,
    )
    members_out = [
        {
            "role": m["role"],
            "principal": {
                "id": str(m["principal_id"]),
                "auth_subject": m["auth_subject"],
                "display_name": m["display_name"],
                "principal_type": m["principal_type"],
            },
        }
        for m in members
    ]

    ai_config = execute_one(
        "SELECT * FROM state.campaign_settings WHERE campaign_id = %s", cid
    )
    ai_config = {k: _jsonify(v) for k, v in (ai_config or {}).items()} or None

    maps = _rows("state.maps", "campaign_id = %s", cid)
    map_ids = [m["id"] for m in maps]
    map_nodes = (
        _rows("state.map_nodes", "map_id = ANY(%s::uuid[])", (map_ids,)) if map_ids else []
    )
    map_pois = (
        _rows("state.map_pois", "map_id = ANY(%s::uuid[])", (map_ids,)) if map_ids else []
    )
    map_decorations = (
        _rows("state.map_decorations", "map_id = ANY(%s::uuid[])", (map_ids,)) if map_ids else []
    )

    entities = _rows("state.entities", "campaign_id = %s", cid)
    sessions = _rows("state.sessions", "campaign_id = %s", cid)

    encounters = _rows("state.encounters", "campaign_id = %s", cid)
    enc_ids = [e["id"] for e in encounters]
    encounter_slots = (
        _rows("state.encounter_slots", "encounter_id = ANY(%s::uuid[])", (enc_ids,))
        if enc_ids
        else []
    )

    ledger_events = _rows(
        "ledger.session_ledger", "campaign_id = %s ORDER BY seq_id", cid
    )

    return {
        "campaign": {k: _jsonify(v) for k, v in campaign.items()},
        "members": members_out,
        "ai_config": ai_config,
        "maps": maps,
        "map_nodes": map_nodes,
        "map_pois": map_pois,
        "map_decorations": map_decorations,
        "entities": entities,
        "sessions": sessions,
        "encounters": encounters,
        "encounter_slots": encounter_slots,
        "ledger_events": ledger_events,
    }


# ------------------------------------------------------------------------
# Import
# ------------------------------------------------------------------------

def _ensure_principal(conn, principal_spec: dict) -> str:
    """Find an existing principal by auth_subject, or create one.

    Returns the destination machine's principal_id (UUID string).
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM state.principals WHERE auth_subject = %s LIMIT 1",
        (principal_spec["auth_subject"],),
    )
    row = cur.fetchone()
    if row:
        cur.close()
        return str(row[0])
    cur.execute(
        """
        INSERT INTO state.principals (principal_type, display_name, auth_subject, is_active)
        VALUES (%s, %s, %s, true)
        RETURNING id
        """,
        (principal_spec["principal_type"], principal_spec["display_name"], principal_spec["auth_subject"]),
    )
    new_id = str(cur.fetchone()[0])
    cur.close()
    return new_id


def _purge_campaign(conn, campaign_id: str):
    """Same cascade-delete logic as /api/campaigns/<id>/purge, but run on the
    caller's connection so it joins the import transaction."""
    cur = conn.cursor()
    cid = (campaign_id,)
    cur.execute("ALTER TABLE state.sessions DISABLE TRIGGER trg_archive_session")
    try:
        for sql in (
            "DELETE FROM ledger.session_ledger WHERE campaign_id = %s",
            "DELETE FROM state.encounter_slots WHERE encounter_id IN (SELECT id FROM state.encounters WHERE campaign_id = %s)",
            "DELETE FROM state.conditions WHERE entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR encounter_id IN (SELECT id FROM state.encounters WHERE campaign_id = %s)",
            "DELETE FROM state.intents WHERE campaign_id = %s",
            "DELETE FROM state.interventions WHERE campaign_id = %s",
            "DELETE FROM state.divine_standings WHERE campaign_id = %s",
            "DELETE FROM state.faction_memberships WHERE entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR faction_id IN (SELECT id FROM state.factions WHERE campaign_id = %s)",
            "DELETE FROM state.faction_wars WHERE campaign_id = %s",
            "DELETE FROM state.bounties WHERE campaign_id = %s",
            "DELETE FROM state.shop_inventory WHERE shop_id IN (SELECT id FROM state.shops WHERE campaign_id = %s) OR item_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
            "DELETE FROM state.location_metrics WHERE location_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
            "DELETE FROM state.property_ownership WHERE property_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s) OR owner_entity_id IN (SELECT id FROM state.entities WHERE campaign_id = %s)",
            "DELETE FROM state.reaction_triggers WHERE campaign_id = %s",
            "DELETE FROM state.entity_death_history WHERE campaign_id = %s",
            "DELETE FROM state.session_characters WHERE session_id IN (SELECT id FROM state.sessions WHERE campaign_id = %s)",
            "DELETE FROM state.price_modifiers WHERE campaign_id = %s",
            "DELETE FROM state.encounters WHERE campaign_id = %s",
            "DELETE FROM state.shops WHERE campaign_id = %s",
            "DELETE FROM state.factions WHERE campaign_id = %s",
            "DELETE FROM state.map_nodes WHERE map_id IN (SELECT id FROM state.maps WHERE campaign_id = %s)",
            "DELETE FROM state.map_decorations WHERE map_id IN (SELECT id FROM state.maps WHERE campaign_id = %s)",
            "DELETE FROM state.map_pois WHERE map_id IN (SELECT id FROM state.maps WHERE campaign_id = %s)",
            "DELETE FROM state.entities WHERE campaign_id = %s",
            "DELETE FROM state.maps WHERE campaign_id = %s",
            "DELETE FROM state.story_state_history WHERE session_id IN (SELECT id FROM state.sessions WHERE campaign_id = %s)",
            "DELETE FROM state.story_state WHERE campaign_id = %s",
            "DELETE FROM state.session_archives WHERE campaign_id = %s",
            "DELETE FROM state.sessions WHERE campaign_id = %s",
            "DELETE FROM state.rag_chunks WHERE campaign_id = %s",
            "DELETE FROM state.rag_documents WHERE campaign_id = %s",
            "DELETE FROM state.campaign_settings WHERE campaign_id = %s",
            "DELETE FROM state.campaign_members WHERE campaign_id = %s",
            "DELETE FROM state.campaigns WHERE id = %s",
        ):
            cur.execute(sql, cid * sql.count("%s"))
    finally:
        cur.execute("ALTER TABLE state.sessions ENABLE TRIGGER trg_archive_session")
        cur.close()


def _insert_row(conn, table: str, row: dict, principal_remap: dict = None,
                jsonb_cols: tuple = (), array_cols: tuple = ()) -> None:
    """Insert one row, remapping principal_ids, json-encoding jsonb cols, and
    leaving array columns as Python lists for psycopg2 to handle natively."""
    cols = list(row.keys())
    vals = []
    for c in cols:
        v = row[c]
        if v is not None and c in ("controller_principal_id",) and principal_remap:
            v = principal_remap.get(str(v), v)
        if c in jsonb_cols and not isinstance(v, str):
            v = json.dumps(v) if v is not None else None
        # Array columns: psycopg2 adapts Python lists to PG arrays natively.
        # If we got a JSON-string back from a previous round-trip, parse it.
        if c in array_cols and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        vals.append(v)
    placeholders = ", ".join(
        f"%s::jsonb" if c in jsonb_cols else "%s"
        for c in cols
    )
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        tuple(vals),
    )
    cur.close()


def import_campaign(payload: dict, *, replace: bool = False) -> str:
    """Import a campaign from an export() payload.

    If a campaign with the same id already exists, behavior depends on
    `replace`: True means cascade-purge first; False means raise.

    Returns the imported campaign_id.
    """
    campaign = payload["campaign"]
    cid = campaign["id"]

    existing = execute_one("SELECT id FROM state.campaigns WHERE id = %s", (cid,))
    if existing and not replace:
        raise ValueError(
            f"A campaign with id {cid} already exists. Set replace=True to overwrite."
        )

    conn = get_connection()
    try:
        if existing:
            _purge_campaign(conn, cid)

        # Resolve all principals referenced by members or entities.
        principal_remap: dict[str, str] = {}
        for m in payload.get("members", []):
            spec = m["principal"]
            principal_remap[spec["id"]] = _ensure_principal(conn, spec)

        # Re-insert in the right order: parent rows before children.
        _insert_row(conn, "state.campaigns", campaign)
        for m in payload.get("members", []):
            spec = m["principal"]
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO state.campaign_members (campaign_id, principal_id, role)
                VALUES (%s, %s, %s)
                ON CONFLICT (campaign_id, principal_id) DO NOTHING
                """,
                (cid, principal_remap[spec["id"]], m["role"]),
            )
            cur.close()

        if payload.get("ai_config"):
            _insert_row(conn, "state.campaign_settings", payload["ai_config"],
                        jsonb_cols=("settings",))

        for m in payload.get("maps", []):
            _insert_row(conn, "state.maps", m)
        for n in payload.get("map_nodes", []):
            _insert_row(conn, "state.map_nodes", n, jsonb_cols=("terrain",))
        for p in payload.get("map_pois", []):
            _insert_row(conn, "state.map_pois", p, jsonb_cols=("metadata",))
        for d in payload.get("map_decorations", []):
            _insert_row(conn, "state.map_decorations", d, jsonb_cols=("metadata",))

        for e in payload.get("entities", []):
            _insert_row(conn, "state.entities", e,
                        principal_remap=principal_remap,
                        jsonb_cols=("public_sheet", "secret_sheet"))

        for s in payload.get("sessions", []):
            _insert_row(conn, "state.sessions", s)
        for enc in payload.get("encounters", []):
            _insert_row(conn, "state.encounters", enc)
        for slot in payload.get("encounter_slots", []):
            _insert_row(conn, "state.encounter_slots", slot)

        for ev in payload.get("ledger_events", []):
            # seq_id is GENERATED ALWAYS — drop it and let Postgres re-assign.
            # Event ordering is preserved because we insert in original seq_id
            # order (the exporter ORDER BY seq_id, and Python iteration is
            # ordered). parent_event_id references event_id (UUID), not seq_id,
            # so the parent chain survives.
            ev = {k: v for k, v in ev.items() if k != "seq_id"}
            _insert_row(conn, "ledger.session_ledger", ev,
                        jsonb_cols=("payload",),
                        array_cols=("domain_tags", "visible_to"))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return cid

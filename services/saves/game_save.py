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


def _json_rows(table: str, where: str, params: tuple) -> list[dict]:
    """Serialize rows in Postgres so UUID arrays retain their list shape."""
    rows = execute_query(
        f"SELECT to_jsonb(export_row) AS export_row "
        f"FROM {table} AS export_row WHERE {where}",
        params,
    )
    return [row["export_row"] for row in rows]


def _jsonify(v):
    """Coerce DB values into JSON-safe shapes."""
    if v is None:
        return None
    if isinstance(v, uuid.UUID):
        return str(v)
    if hasattr(v, "isoformat"):  # datetime, date
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonify(value) for k, value in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonify(value) for value in v]
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


def _referenced_principal_ids(payload: dict) -> set[str]:
    """Collect every principal UUID stored as a relational reference."""
    referenced = set()
    for member in payload.get("members", []):
        principal_id = member.get("principal", {}).get("id")
        if principal_id:
            referenced.add(str(principal_id))
    for entity in payload.get("entities", []):
        principal_id = entity.get("controller_principal_id")
        if principal_id:
            referenced.add(str(principal_id))
    for event in payload.get("ledger_events", []):
        sender_id = event.get("sender_principal_id")
        if sender_id:
            referenced.add(str(sender_id))
        visible_to = event.get("visible_to") or []
        if not isinstance(visible_to, (list, tuple)):
            raise ValueError(
                "ledger event visible_to must be an array of principal IDs"
            )
        for principal_id in visible_to:
            referenced.add(str(principal_id))
    return referenced


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
        _rows("state.map_nodes", "map_id = ANY(%s::uuid[])", (map_ids,))
        if map_ids
        else []
    )
    map_pois = (
        _rows("state.map_pois", "map_id = ANY(%s::uuid[])", (map_ids,))
        if map_ids
        else []
    )
    map_decorations = (
        _rows("state.map_decorations", "map_id = ANY(%s::uuid[])", (map_ids,))
        if map_ids
        else []
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

    ledger_events = _json_rows(
        "ledger.session_ledger", "campaign_id = %s ORDER BY seq_id", cid
    )
    rag_embedding_profiles = _rows(
        "state.rag_embedding_profiles", "campaign_id = %s", cid
    )
    rag_documents = _rows("state.rag_documents", "campaign_id = %s", cid)
    rag_chunks = _rows("state.rag_chunks", "campaign_id = %s", cid)

    payload = {
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
        "rag_embedding_profiles": rag_embedding_profiles,
        "rag_documents": rag_documents,
        "rag_chunks": rag_chunks,
    }

    principal_ids = sorted(_referenced_principal_ids(payload))
    principals = (
        execute_query(
            """
            SELECT id, auth_subject, display_name, principal_type
            FROM state.principals
            WHERE id = ANY(%s::uuid[])
            ORDER BY auth_subject, id
            """,
            (principal_ids,),
        )
        if principal_ids
        else []
    )
    payload["principals"] = [
        {key: _jsonify(value) for key, value in principal.items()}
        for principal in principals
    ]
    return payload


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
        (
            principal_spec["principal_type"],
            principal_spec["display_name"],
            principal_spec["auth_subject"],
        ),
    )
    new_id = str(cur.fetchone()[0])
    cur.close()
    return new_id


def _purge_campaign(conn, campaign_id: str):
    """Delete the target campaign inside the caller's import transaction."""
    from services.campaigns.lifecycle import hard_delete_campaign

    hard_delete_campaign(campaign_id, conn=conn)


def _principal_specs(payload: dict) -> dict[str, dict]:
    """Index portable principal metadata from current and legacy saves."""
    specs = {
        str(spec["id"]): spec
        for spec in payload.get("principals", [])
        if spec.get("id")
    }
    for member in payload.get("members", []):
        spec = member.get("principal") or {}
        if spec.get("id"):
            specs[str(spec["id"])] = spec
    return specs


def _principal_exists(conn, principal_id: str) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM state.principals WHERE id = %s", (principal_id,))
    exists = cur.fetchone() is not None
    cur.close()
    return exists


def _complete_principal_remap(
    conn, payload: dict, principal_remap: dict[str, str]
) -> None:
    """Require a destination identity for each UUID in the save graph."""
    for source_id in sorted(_referenced_principal_ids(payload)):
        if source_id in principal_remap:
            continue
        if _principal_exists(conn, source_id):
            # Legacy saves omitted non-member metadata. They remain importable
            # on the source machine while cross-machine imports fail closed.
            principal_remap[source_id] = source_id
            continue
        raise ValueError(
            "Save file is missing portable principal metadata for referenced "
            f"principal {source_id}"
        )


def _remap_principal_value(value, principal_remap: dict[str, str], column: str) -> str:
    source_id = str(value)
    if source_id not in principal_remap:
        raise ValueError(f"No destination principal mapping for {column}={source_id}")
    return principal_remap[source_id]


def _insert_row(
    conn,
    table: str,
    row: dict,
    principal_remap: dict = None,
    jsonb_cols: tuple = (),
    array_cols: tuple = (),
) -> None:
    """Insert one row, remapping principal_ids, json-encoding jsonb cols, and
    leaving array columns as Python lists for psycopg2 to handle natively."""
    cols = list(row.keys())
    vals = []
    for c in cols:
        v = row[c]
        # Array columns: psycopg2 adapts Python lists to PG arrays natively.
        # If we got a JSON-string back from a previous round-trip, parse it.
        if c in array_cols and isinstance(v, str):
            try:
                v = json.loads(v)
            except json.JSONDecodeError:
                pass
        if (
            v is not None
            and c in ("controller_principal_id", "sender_principal_id")
            and principal_remap
        ):
            v = _remap_principal_value(v, principal_remap, c)
        if v is not None and c == "visible_to" and principal_remap:
            if not isinstance(v, (list, tuple)):
                raise ValueError("visible_to must be an array of principal IDs")
            v = [_remap_principal_value(item, principal_remap, c) for item in v]
        if c in jsonb_cols and not isinstance(v, str):
            v = json.dumps(v) if v is not None else None
        vals.append(v)
    placeholders = ", ".join(
        "%s::jsonb" if c in jsonb_cols else "%s::uuid[]" if c == "visible_to" else "%s"
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

        # Resolve every principal reference by stable auth_subject.
        principal_remap: dict[str, str] = {}
        for source_id, spec in _principal_specs(payload).items():
            principal_remap[source_id] = _ensure_principal(conn, spec)
        _complete_principal_remap(conn, payload, principal_remap)

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
            _insert_row(
                conn,
                "state.campaign_settings",
                payload["ai_config"],
                jsonb_cols=("settings",),
            )

        for profile in payload.get("rag_embedding_profiles", []):
            _insert_row(conn, "state.rag_embedding_profiles", profile)

        for m in payload.get("maps", []):
            _insert_row(conn, "state.maps", m)
        for n in payload.get("map_nodes", []):
            _insert_row(conn, "state.map_nodes", n, jsonb_cols=("terrain",))
        for p in payload.get("map_pois", []):
            _insert_row(conn, "state.map_pois", p, jsonb_cols=("metadata",))
        for d in payload.get("map_decorations", []):
            _insert_row(conn, "state.map_decorations", d, jsonb_cols=("metadata",))

        for e in payload.get("entities", []):
            _insert_row(
                conn,
                "state.entities",
                e,
                principal_remap=principal_remap,
                jsonb_cols=("public_sheet", "secret_sheet"),
            )

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
            _insert_row(
                conn,
                "ledger.session_ledger",
                ev,
                principal_remap=principal_remap,
                jsonb_cols=("payload",),
                array_cols=("domain_tags", "visible_to"),
            )

        for doc in payload.get("rag_documents", []):
            _insert_row(conn, "state.rag_documents", doc)
        for chunk in payload.get("rag_chunks", []):
            _insert_row(conn, "state.rag_chunks", chunk, jsonb_cols=("metadata",))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return cid

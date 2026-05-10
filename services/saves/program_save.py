"""Program save = installation-wide config.

Contents:
- state.global_settings rows (API keys, default image-gen settings, etc.)
- HUMAN principal records (so the LocalPlayer auth_subject survives)

Game saves reference principals by auth_subject; a program save is what
gives the destination machine those auth_subjects in the first place.
"""

import json
import uuid

from shared.db.connection import get_connection, execute_query


def export_program() -> dict:
    """Snapshot everything that should follow the user across installs."""
    settings_rows = execute_query(
        "SELECT key, value, updated_at FROM state.global_settings ORDER BY key"
    )
    principals_rows = execute_query(
        "SELECT id, principal_type, display_name, auth_subject, is_active "
        "FROM state.principals WHERE principal_type = 'HUMAN'"
    )
    return {
        "global_settings": [
            {
                "key": r["key"],
                "value": r["value"],
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
            for r in settings_rows
        ],
        "principals": [
            {
                "id": str(p["id"]),
                "principal_type": p["principal_type"],
                "display_name": p["display_name"],
                "auth_subject": p["auth_subject"],
                "is_active": p["is_active"],
            }
            for p in principals_rows
        ],
    }


def import_program(payload: dict) -> dict:
    """Restore global settings + HUMAN principals.

    Settings are upserted by key. Principals are upserted by auth_subject —
    if the destination machine already has a principal with the same
    auth_subject we don't overwrite their id (downstream FKs would break),
    but we update display_name and is_active.

    Returns a summary count for the UI to display.
    """
    settings = payload.get("global_settings", []) or []
    principals = payload.get("principals", []) or []

    conn = get_connection()
    try:
        cur = conn.cursor()
        for s in settings:
            val = s["value"]
            if not isinstance(val, str):
                val = json.dumps(val)
            cur.execute(
                """
                INSERT INTO state.global_settings (key, value, updated_at)
                VALUES (%s, %s::jsonb, now())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = now()
                """,
                (s["key"], val),
            )
        for p in principals:
            cur.execute(
                """
                INSERT INTO state.principals (principal_type, display_name, auth_subject, is_active)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (auth_subject) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    is_active = EXCLUDED.is_active,
                    updated_at = now()
                """,
                (p["principal_type"], p["display_name"], p["auth_subject"], p.get("is_active", True)),
            )
        conn.commit()
        cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {
        "settings_imported": len(settings),
        "principals_imported": len(principals),
    }

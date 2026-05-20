"""Program save = installation-wide config.

Contents:
- state.global_settings rows (API keys, default image-gen settings, etc.)
- HUMAN principal records (so the LocalPlayer auth_subject survives)

Game saves reference principals by auth_subject; a program save is what
gives the destination machine those auth_subjects in the first place.
"""

import json

from shared.db.connection import get_connection, execute_query


def export_program() -> dict:
    """Snapshot everything that should follow the user across installs.

    Decrypts vault-protected values before writing them into the save —
    each installation has its own vault key, so we can't share encrypted
    blobs across machines. The .ttdm wrapper is itself passphrase-encrypted,
    so the cleartext only exists inside the encrypted save file.
    """
    from services.saves.vault import decrypt_dict_values

    settings_rows = execute_query(
        "SELECT key, value, updated_at FROM state.global_settings ORDER BY key"
    )
    principals_rows = execute_query(
        "SELECT id, principal_type, display_name, auth_subject, is_active "
        "FROM state.principals WHERE principal_type = 'HUMAN'"
    )

    settings_out = []
    for r in settings_rows:
        value = r["value"]
        # Strip vault wrappers so the file is portable across machines.
        if isinstance(value, dict):
            value = decrypt_dict_values(value)
        settings_out.append(
            {
                "key": r["key"],
                "value": value,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
        )

    return {
        "global_settings": settings_out,
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
    from services.saves.vault import encrypt_str

    settings = payload.get("global_settings", []) or []
    principals = payload.get("principals", []) or []

    def _maybe_reencrypt(key: str, value):
        """The export decrypted vault-wrapped values; re-encrypt them with
        this machine's vault key on import. Affects only the api_keys family."""
        if not isinstance(value, dict):
            return value
        if key == "api_keys" or key.endswith("_api_keys"):
            return {
                k: (encrypt_str(v) if v and isinstance(v, str) else v)
                for k, v in value.items()
            }
        return value

    conn = get_connection()
    try:
        cur = conn.cursor()
        for s in settings:
            val = _maybe_reencrypt(s["key"], s["value"])
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
                (
                    p["principal_type"],
                    p["display_name"],
                    p["auth_subject"],
                    p.get("is_active", True),
                ),
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

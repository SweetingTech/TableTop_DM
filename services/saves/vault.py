"""At-rest encryption for sensitive strings (API keys).

The server needs to *use* API keys (decrypt them and send in
Authorization headers), so they can't be hashed. Instead we encrypt them
with a per-installation Fernet key that lives outside the database:

    .local-run/vault.key   (host filesystem, gitignored)

`.local-run/` is project-relative and not inside the Docker container, so:
- `docker compose down -v` doesn't touch it
- backing up the project folder backs up the vault key
- moving the project to a new machine carries the vault key with it

If you lose the vault key, encrypted values become unrecoverable garbage
and you have to re-enter the API keys. That's the tradeoff with
machine-local encryption — it survives reboots and DB wipes, but not
losing the key file itself.

For *cross-machine* portability of API keys, use the program save export
flow — that decrypts the keys before writing them into the .ttdm file
(which is itself passphrase-encrypted), and re-encrypts on import using
the destination machine's vault key.

API:
    encrypt_str(s)      -> "vault:v1:<fernet-token>"
    decrypt_str(s)      -> original string, or s itself if not encrypted
    is_encrypted(s)     -> True / False
    redact(s)           -> "********" if value present (for safe GET responses)
"""

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


VAULT_PREFIX = "vault:v1:"
_VAULT_KEY_PATH = Path(".local-run/vault.key")
_fernet_cache: Optional[Fernet] = None


def _vault_fernet() -> Fernet:
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache
    # Env var override takes precedence (handy for CI / containerized deploys).
    env_key = os.environ.get("TTDM_VAULT_KEY")
    if env_key:
        _fernet_cache = Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
        return _fernet_cache
    if not _VAULT_KEY_PATH.exists():
        _VAULT_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VAULT_KEY_PATH.write_bytes(Fernet.generate_key())
        try:
            # Tighten permissions where the OS supports it.
            os.chmod(_VAULT_KEY_PATH, 0o600)
        except Exception:
            pass
    _fernet_cache = Fernet(_VAULT_KEY_PATH.read_bytes())
    return _fernet_cache


def is_encrypted(s) -> bool:
    return isinstance(s, str) and s.startswith(VAULT_PREFIX)


def encrypt_str(s: str) -> str:
    """Encrypt a string. Already-encrypted values pass through unchanged so
    we can call this idempotently on save handlers."""
    if not s or not isinstance(s, str):
        return s
    if is_encrypted(s):
        return s
    token = _vault_fernet().encrypt(s.encode("utf-8")).decode("ascii")
    return VAULT_PREFIX + token


def decrypt_str(s: str) -> str:
    """Reverse encrypt_str. Plaintext-passthrough so legacy unencrypted
    values still load (we'll re-encrypt on next save)."""
    if not is_encrypted(s):
        return s
    token = s[len(VAULT_PREFIX):].encode("ascii")
    try:
        return _vault_fernet().decrypt(token).decode("utf-8")
    except InvalidToken:
        raise RuntimeError(
            "Encrypted API key could not be decrypted — the vault key has "
            "changed or .local-run/vault.key is missing. Re-enter the key "
            "in Control Plane → API Keys."
        )


def redact(s) -> str:
    """For GET responses. Returns a fixed-length mask so the UI knows there
    *is* a key without leaking the value. ASCII-safe (some Windows consoles
    mangle Unicode dots)."""
    if not s:
        return ""
    return "********"


def encrypt_dict_values(d: dict, *, key_names: Optional[set] = None) -> dict:
    """Walk a dict and encrypt string values. If key_names is given, only
    encrypt values whose dict key is in that set. Used by API-key blobs
    where the whole map is sensitive."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, str) and (key_names is None or k in key_names):
            out[k] = encrypt_str(v)
        elif isinstance(v, dict):
            out[k] = encrypt_dict_values(v, key_names=key_names)
        else:
            out[k] = v
    return out


def decrypt_dict_values(d: dict) -> dict:
    """Inverse of encrypt_dict_values — pulls plaintext back out for use."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, str) and is_encrypted(v):
            out[k] = decrypt_str(v)
        elif isinstance(v, dict):
            out[k] = decrypt_dict_values(v)
        else:
            out[k] = v
    return out


def redact_dict_values(d: dict, *, sensitive_keys: Optional[set] = None) -> dict:
    """Replace sensitive values with redaction markers for safe API GET
    responses. If sensitive_keys is None, redact every encrypted value."""
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            out[k] = redact_dict_values(v, sensitive_keys=sensitive_keys)
        elif isinstance(v, str):
            if sensitive_keys is not None and k in sensitive_keys:
                out[k] = redact(v)
            elif is_encrypted(v):
                out[k] = redact(v)
            else:
                out[k] = v
        else:
            out[k] = v
    return out

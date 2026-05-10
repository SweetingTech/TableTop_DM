"""Passphrase-encrypted save file format for TableTop DM.

File layout (one self-describing blob):

    ttdm-save:v1
    <one-line JSON header>
    <newline>
    <base64 fernet token>

Header fields:
    format:           "TTDM_SAVE"
    version:          int (currently 1)
    kind:             "game" | "program"
    created_at:       ISO 8601 UTC
    schema_version:   the migration version the export came from
    kdf:              "pbkdf2-sha256"
    kdf_iterations:   integer (NIST recommends ≥600k)
    kdf_salt_b64:     16 random bytes base64

The body is Fernet-encrypted JSON. Fernet = AES-128-CBC + HMAC-SHA256, with
a per-token IV. The encryption key is derived from the user's passphrase
plus the header's salt via PBKDF2-HMAC-SHA256.

A wrong passphrase decrypts to garbage and Fernet's HMAC will reject it,
so attempted decryption surfaces a clear "wrong passphrase" error rather
than corrupted data.
"""

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


FILE_MAGIC = b"ttdm-save:v1\n"
KDF_ITERATIONS = 600_000  # NIST 2023 floor for PBKDF2-HMAC-SHA256
SCHEMA_VERSION = 12       # bump when migrations 013+ land
SUPPORTED_KINDS = ("game", "program")


class SaveFileError(Exception):
    """Anything that goes wrong reading or writing a save file."""


def _derive_key(passphrase: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt_save(payload: dict, *, kind: str, passphrase: str) -> bytes:
    """Encode + encrypt a save dict into the wire-format bytes that get
    downloaded to the user's filesystem."""
    if kind not in SUPPORTED_KINDS:
        raise SaveFileError(f"Unknown save kind: {kind}")
    if not passphrase:
        raise SaveFileError("Passphrase is required")
    if not isinstance(payload, dict):
        raise SaveFileError("Payload must be a dict")

    salt = os.urandom(16)
    header = {
        "format": "TTDM_SAVE",
        "version": 1,
        "kind": kind,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": SCHEMA_VERSION,
        "kdf": "pbkdf2-sha256",
        "kdf_iterations": KDF_ITERATIONS,
        "kdf_salt_b64": base64.b64encode(salt).decode("ascii"),
    }
    key = _derive_key(passphrase, salt, KDF_ITERATIONS)
    token = Fernet(key).encrypt(json.dumps(payload, default=str).encode("utf-8"))

    return FILE_MAGIC + json.dumps(header).encode("utf-8") + b"\n" + token


def decrypt_save(blob: bytes, *, passphrase: str, expected_kind: str = None) -> dict:
    """Inverse of encrypt_save. Returns the original payload dict.

    Raises SaveFileError with a clear message on:
    - missing/wrong magic header
    - corrupted header JSON
    - wrong passphrase
    - kind mismatch (when expected_kind is provided)
    """
    if not blob.startswith(FILE_MAGIC):
        raise SaveFileError("Not a TableTop DM save file (missing magic header).")
    rest = blob[len(FILE_MAGIC):]
    try:
        header_line, _, token = rest.partition(b"\n")
        header = json.loads(header_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SaveFileError(f"Save file header is corrupted: {e}")

    if header.get("format") != "TTDM_SAVE":
        raise SaveFileError(f"Unexpected file format: {header.get('format')!r}")
    if header.get("version") != 1:
        raise SaveFileError(f"Unsupported save file version: {header.get('version')}")
    kind = header.get("kind")
    if kind not in SUPPORTED_KINDS:
        raise SaveFileError(f"Unknown save kind: {kind}")
    if expected_kind and kind != expected_kind:
        raise SaveFileError(f"Wrong save kind: expected {expected_kind}, got {kind}")
    try:
        salt = base64.b64decode(header["kdf_salt_b64"])
        iterations = int(header.get("kdf_iterations") or KDF_ITERATIONS)
    except Exception:
        raise SaveFileError("Save file KDF parameters are missing or corrupted.")
    if not token:
        raise SaveFileError("Save file body is empty.")

    key = _derive_key(passphrase, salt, iterations)
    try:
        plaintext = Fernet(key).decrypt(token)
    except InvalidToken:
        raise SaveFileError(
            "Decryption failed. Either the passphrase is wrong or the file is corrupted."
        )
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SaveFileError(f"Decrypted payload is not valid JSON: {e}")


def peek_header(blob: bytes) -> dict[str, Any]:
    """Return the header without attempting decryption. Useful for showing
    metadata ('this is a game save from 2026-05-10') before asking for the
    passphrase."""
    if not blob.startswith(FILE_MAGIC):
        raise SaveFileError("Not a TableTop DM save file.")
    header_line, _, _ = blob[len(FILE_MAGIC):].partition(b"\n")
    try:
        return json.loads(header_line.decode("utf-8"))
    except Exception as e:
        raise SaveFileError(f"Header parse error: {e}")

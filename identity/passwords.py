from __future__ import annotations

import base64
import hashlib
import hmac
import os

SCHEME = "scrypt"
N = 2**14
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32


def hash_password(password: str, *, allow_bootstrap_default: bool = False) -> str:
    if not allow_bootstrap_default:
        validate_password(password)
    salt = os.urandom(SALT_BYTES)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=KEY_BYTES)
    return "$".join(
        (
            SCHEME,
            str(N),
            str(R),
            str(P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_text, expected_text = encoded.split("$", 5)
        if scheme != SCHEME:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(expected, actual)
    except (ValueError, TypeError):
        return False


def validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    if len(password) > 256:
        raise ValueError("password must contain no more than 256 characters")
    if password.casefold() in {"admin123", "password", "password123", "administrator"}:
        raise ValueError("choose a password that is not a common default")

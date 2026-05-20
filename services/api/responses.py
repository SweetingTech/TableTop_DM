from __future__ import annotations

import os
import traceback
import uuid

from flask import jsonify


def debug_errors_enabled() -> bool:
    return os.environ.get("TTDM_DEBUG", "0").lower() in {"1", "true", "yes", "on"}


def json_error(message: str, status: int = 400, *, exc: Exception | None = None):
    payload = {"error": message}
    if exc is not None and debug_errors_enabled():
        payload["detail"] = str(exc)
        payload["trace"] = traceback.format_exc()
    return jsonify(payload), status


def serialize(obj):
    if isinstance(obj, dict):
        return {k: serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (bytes, memoryview)):
        return str(bytes(obj))
    return obj

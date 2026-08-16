from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import uuid
from typing import Any


def serialize(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def row_dict(row: dict | None) -> dict:
    return serialize(dict(row or {}))

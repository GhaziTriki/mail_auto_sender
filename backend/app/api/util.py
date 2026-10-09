from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from ..errors import NotFound


def oid(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as e:
        raise NotFound("Not found", code="not_found") from e


def ser(value: Any) -> Any:
    """Make a Mongo document JSON-safe. `_id` becomes `id`; ObjectIds become strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "_id":
                out["id"] = str(v)
            elif k in ("secret_enc", "user_id", "name_lower"):
                continue
            else:
                out[k] = ser(v)
        return out
    if isinstance(value, (list, tuple)):
        return [ser(v) for v in value]
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value

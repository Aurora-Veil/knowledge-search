"""Convert BSON types to JSON-serializable types."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from bson import ObjectId


def to_jsonable(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: to_jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return v


__all__ = ["to_jsonable"]

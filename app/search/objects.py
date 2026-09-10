from __future__ import annotations

from typing import Any, Optional

from ..config import COLLECTION_BY_TYPE
from ..db import get_db
from ..serializers import to_jsonable


def get_object(object_type: str, oirf_id: str, project_id: int) -> Optional[dict[str, Any]]:
    """
    full object data
    not exist → None
    unvalid type → ValueError
    """
    if object_type not in COLLECTION_BY_TYPE:
        raise ValueError(f"unknown object_type: {object_type!r} (expected one of {list(COLLECTION_BY_TYPE)})")

    doc = get_db()[COLLECTION_BY_TYPE[object_type]].find_one({"oirf_id": oirf_id, "project_id": project_id})
    if doc is None:
        return None
    
    # Convert the document to a JSON-serializable format
    obj = to_jsonable(doc)
    obj.pop("_id", None)
    if "id" not in obj:
        obj["id"] = to_jsonable(doc.get("_id"))
    return obj


__all__ = ["get_object"]

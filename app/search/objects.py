from __future__ import annotations

from typing import Any, Optional

from ..config import COLLECTION_BY_TYPE
from ..db import get_db
from ..serializers import to_jsonable


def get_object(object_type: str, oirf_id: str, project_id: int) -> Optional[dict[str, Any]]:
    """完整对象（JSON 安全）；不存在返回 None，object_type 非法抛 ValueError。"""
    if object_type not in COLLECTION_BY_TYPE:
        raise ValueError(f"unknown object_type: {object_type!r} (expected one of {list(COLLECTION_BY_TYPE)})")

    doc = get_db()[COLLECTION_BY_TYPE[object_type]].find_one({"oirf_id": oirf_id, "project_id": project_id})
    if doc is None:
        return None

    obj = to_jsonable(doc)
    obj.pop("_id", None)  # id 已等于 _id，去重
    if "id" not in obj:
        obj["id"] = to_jsonable(doc.get("_id"))
    return obj


__all__ = ["get_object"]

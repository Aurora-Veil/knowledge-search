"""§5.2 完整对象：按 object_type + oirf_id + project_id 回 Mongo 取**完整权威字段**。

搜索命中的卡片只带可搜/可筛字段（`_source` 白名单），长文本/完整 reasoning/responsibility/lifecycle 等
需回 Mongo 补全。**必须限定 project_id**（同号 oirf_id 跨项目会串号）。
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import COLLECTION_BY_TYPE
from ..db import get_db
from ..serializers import to_jsonable


def get_object(object_type: str, oirf_id: str, project_id: int) -> Optional[dict[str, Any]]:
    """返回完整对象（已序列化 JSON 安全）；不存在返回 None。

    object_type 非法时抛 ValueError（可被上层路由转 400）。
    """
    if object_type not in COLLECTION_BY_TYPE:
        raise ValueError(f"unknown object_type: {object_type!r} (expected one of {list(COLLECTION_BY_TYPE)})")

    doc = get_db()[COLLECTION_BY_TYPE[object_type]].find_one(
        {"oirf_id": oirf_id, "project_id": project_id}
    )
    if doc is None:
        return None

    obj = to_jsonable(doc)
    obj.pop("_id", None)  # id 已等于 _id（ObjectId），去重；公开标识用 `id`
    if "id" not in obj:  # 防御：万一缺 id，用 _id 值补上
        obj["id"] = to_jsonable(doc.get("_id"))
    return obj


__all__ = ["get_object"]

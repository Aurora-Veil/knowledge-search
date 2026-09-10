"""写后单条同步：sync_one(project_id, oirf_id, type_) —— 有则 upsert，Mongo 已无则从 ES 删除。

约定：ES 不可用时把异常抛给调用方，不静默；不启长连接（Change Streams 不在本层）。
"""
from __future__ import annotations

from typing import Any

from elasticsearch import NotFoundError

from ..config import COLLECTION_BY_TYPE, INDEX_BY_TYPE
from ..db import resolve_db, resolve_es
from ..serializers import to_jsonable
from . import admin


def find_doc(project_id: int, oirf_id: str, type_: str, db=None) -> dict[str, Any] | None:
    """按 (project_id, oirf_id) 取权威文档。"""
    coll = resolve_db(db)[COLLECTION_BY_TYPE[type_]]
    return coll.find_one({"project_id": project_id, "oirf_id": oirf_id})


def es_ids(project_id: int, oirf_id: str, type_: str, es=None) -> list[str]:
    """ES 里该对象的 _id。

    对象已从 Mongo 删除时 _id 无从得知，只能按 (project_id, oirf_id) 反查；
    两个字段在 mapping 里都是 keyword，故 project_id 要转成字符串再 term。
    """
    body = {
        "query": {"bool": {"filter": [
            {"term": {"project_id": str(project_id)}},
            {"term": {"oirf_id": oirf_id}},
        ]}},
        "size": 10,
        "source": False,
    }
    res = resolve_es(es).search(index=INDEX_BY_TYPE[type_], **body)
    return [h["_id"] for h in res["hits"]["hits"]]


def sync_one(project_id: int, oirf_id: str, type_: str, db=None, es=None) -> dict[str, Any]:
    """写库后调用：更新/删除单条 ES 文档。返回动作与定位信息，供调用方打印/审计。"""
    es = resolve_es(es)
    index = INDEX_BY_TYPE[type_]
    doc = find_doc(project_id, oirf_id, type_, db)
    has_index = admin.exists(index, es)

    if doc is None:
        if not has_index:
            # 索引都不存在 = 没有可删的东西（直接查会抛 index_not_found），如实回报为"无需动作"
            return {"action": "absent", "index": index, "ids": [], "missing_index": True,
                    "created_index": False, "project_id": project_id, "oirf_id": oirf_id}
        ids = es_ids(project_id, oirf_id, type_, es)
        for i in ids:
            try:
                es.delete(index=index, id=i)
            except NotFoundError:  # 已被别处删掉 = 已达成，忽略
                pass
        if ids:
            es.indices.refresh(index=index)
        return {"action": "deleted" if ids else "absent", "index": index, "ids": ids,
                "missing_index": False, "created_index": False,
                "project_id": project_id, "oirf_id": oirf_id}

    created_index = False
    if not has_index:
        # 不能直接往不存在的索引写：ES 会按 dynamic 自动建一个没有正确 mapping 的索引
        # （实测与 mapping/*.json 差 59 处，中文分词与字段类型全会错）。
        # 这里按 mapping 文件建好，并把"我建了索引"如实回报给调用方。
        admin.create(index, type_, es)
        created_index = True

    src = to_jsonable(doc)
    sid = str(src.pop("_id", None) or src.get("id"))
    es.index(index=index, id=sid, document=src)
    es.indices.refresh(index=index)  # 让"立刻搜到新值"成立 —— 写后同步的意义就在这
    return {"action": "indexed", "index": index, "id": sid, "created_index": created_index,
            "missing_index": False, "project_id": project_id, "oirf_id": oirf_id}


__all__ = ["find_doc", "es_ids", "sync_one"]

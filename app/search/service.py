from __future__ import annotations

from typing import Any

from ..config import INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .query import build_query
from .rank import fuse
from .response import hit_to_card

# type=all 不能用单条多索引查询直接带 evidence 专属条件（industry/period…），否则 source/viewpoint
# 索引 term 命中 0、整批被过滤 → 丢其他类型。故必须 per-index 建查询再合并（§5.1.1）。


def _page_size(p: dict[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _search_one(type_: str, p: dict[str, Any]) -> dict[str, Any]:
    es = get_es()
    res = es.search(index=INDEX_BY_TYPE[type_], **build_query(type_, p))
    page, size = _page_size(p)
    return {
        "total": res["hits"]["total"]["value"],
        "page": page,
        "size": size,
        "hits": [hit_to_card(h, type_) for h in res["hits"]["hits"]],
    }


def _search_all(p: dict[str, Any]) -> dict[str, Any]:
    es = get_es()
    page, size = _page_size(p)
    need = page * size  # 每索引取够覆盖全局第 page 页的量，再真正合并切页

    pools = []
    total = 0
    for t in OBJECT_TYPES:
        res = es.search(index=INDEX_BY_TYPE[t], **build_query(t, {**p, "page": 1, "size": need}))
        total += res["hits"]["total"]["value"]
        pools.append((t, res["hits"]["hits"], res["hits"].get("max_score")))

    hits = []
    for norm, raw, h, t in fuse(pools, page, size):
        card = hit_to_card(h, t)
        card["score"] = norm     # 归一化分（跨类型可比）
        card["raw_score"] = raw  # 原始 BM25 分（调试）
        hits.append(card)

    return {"total": total, "page": page, "size": size, "hits": hits}


def search(p: dict[str, Any]) -> dict[str, Any]:
    type_ = p.get("type", "all")
    return _search_all(p) if type_ == "all" else _search_one(type_, p)


__all__ = ["search"]

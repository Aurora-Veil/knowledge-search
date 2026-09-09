"""搜索编排：接参 → build_query 本体 → 打 ES → 卡片。

唯一入口 `search(params)`：
- type != all：单索引查询。
- type == all：对三个索引分别建查询（各自只加其 mapping 有的子句）、按 score 合并，再按全局分页取第 page 页。

注意：type=all 不能用"单条多索引查询"直接带 evidence 专属条件（industry/period…），否则 source/viewpoint
索引 term 命中 0、整批被过滤 → 丢其他类型。故必须 per-index 建查询再合并（§5.1.1）。
"""
from __future__ import annotations

from typing import Any

from ..config import INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .query import build_query
from .response import hit_to_card


def _page_size(p: dict[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _search_one(type_: str, p: dict[str, Any]) -> dict[str, Any]:
    es = get_es()
    body = build_query(type_, p)
    res = es.search(index=INDEX_BY_TYPE[type_], **body)
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

    pooled: list[tuple[float, dict[str, Any], str]] = []
    total = 0
    for t in OBJECT_TYPES:
        body = build_query(t, {**p, "page": 1, "size": need})
        res = es.search(index=INDEX_BY_TYPE[t], **body)
        total += res["hits"]["total"]["value"]
        for h in res["hits"]["hits"]:
            pooled.append((h.get("_score") or 0.0, h, t))

    # 按相关度降序合并（各索引权重尺度一致 → 可合并排名）
    pooled.sort(key=lambda x: -x[0])
    start = (page - 1) * size
    sliced = pooled[start : start + size]

    return {
        "total": total,  # 各索引命中数之和（每文档全局唯一，并 = 和）
        "page": page,
        "size": size,
        "hits": [hit_to_card(h, t) for (_s, h, t) in sliced],
    }


def search(p: dict[str, Any]) -> dict[str, Any]:
    type_ = p.get("type", "all")
    if type_ == "all":
        return _search_all(p)
    return _search_one(type_, p)


__all__ = ["search"]

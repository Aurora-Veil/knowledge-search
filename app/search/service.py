from __future__ import annotations

from typing import Any

from ..config import INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .fields import ASSOC_EVIDENCE_IDS_TYPES, ASSOC_SOURCE_IDS_TYPES
from .query import build_query
from .rank import fuse
from .response import hit_to_card

# type=all 不能用单条多索引查询直接带 evidence 专属条件（industry/period…），否则 source/viewpoint
# 索引 term 命中 0、整批被过滤 → 丢其他类型。故必须 per-index 建查询再合并（§5.1.1）。


def _page_size(p: dict[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _applicable_types(p: dict[str, Any], base: tuple[str, ...] | list[str] = OBJECT_TYPES) -> set[str]:
    """给定关联参数，返回可查询的类型集合（取交集）。无关联参数 → base 全量。

    source_ids/evidence_ids 表示"引用/溯源"关系，只有能建立该引用的类型才查询；
    否则该类型无此字段、不做过滤 → 全量泄漏（修正点）。responsible_role 三类通用，不裁剪。
    """
    types = set(base)
    if p.get("source_ids"):
        types &= set(ASSOC_SOURCE_IDS_TYPES)
    if p.get("evidence_ids"):
        types &= set(ASSOC_EVIDENCE_IDS_TYPES)
    return types


def _empty(total: int, p: dict[str, Any]) -> dict[str, Any]:
    page, size = _page_size(p)
    return {"total": total, "page": page, "size": size, "hits": []}


def _search_one(type_: str, p: dict[str, Any]) -> dict[str, Any]:
    if type_ not in _applicable_types(p, base=(type_,)):
        return _empty(0, p)  # 该类型无法满足关联过滤 → 空结果（而非无过滤全量）
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
    types = _applicable_types(p)
    if not types:
        return _empty(0, p)
    need = page * size  # 每索引取够覆盖全局第 page 页的量，再真正合并切页

    pools = []
    total = 0
    for t in OBJECT_TYPES:
        if t not in types:
            continue  # 关联过滤不适用的类型不查询，避免无过滤全量混入
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

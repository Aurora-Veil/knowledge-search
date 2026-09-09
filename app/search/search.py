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
    """type=all：对三索引各自建查询（各自只加其 mapping 有的子句），再合并。

    跨索引不能比原始 BM25 _score：不同索引规模 N 导致 idf 标尺不同（evidence 349 条 vs source/viewpoint 24 条，
    idf 差 ~2 倍），字段/权重拓扑也各异。故用 **max-score 归一化**（score/max_score → 0~1）抹平标尺后再合并排序。
    （见 docs/search-api-design.md §5.1 的 type=all；调 BM25 k1/b 治不了，只改 tf/长度，不碰 idf。）
    """
    es = get_es()
    page, size = _page_size(p)
    need = page * size  # 每索引取够覆盖全局第 page 页的量，再真正合并切页

    pooled: list[tuple[float, float, dict[str, Any], str]] = []  # (norm, raw, hit, type)
    total = 0
    for t in OBJECT_TYPES:
        body = build_query(t, {**p, "page": 1, "size": need})
        res = es.search(index=INDEX_BY_TYPE[t], **body)
        total += res["hits"]["total"]["value"]
        max_score = res["hits"].get("max_score")
        for h in res["hits"]["hits"]:
            raw = h.get("_score") or 0.0
            norm = (raw / max_score) if max_score else 0.0
            pooled.append((norm, raw, h, t))

    # 按归一化分降序合并（各类型同标尺 → 可合并排名）；纯过滤（无 q）时 norm 全 0，保持索引序
    pooled.sort(key=lambda x: -x[0])
    start = (page - 1) * size
    sliced = pooled[start : start + size]

    hits = []
    for norm, raw, h, t in sliced:
        card = hit_to_card(h, t)
        card["score"] = norm    # 覆写为归一化分（跨类型可比）
        card["raw_score"] = raw  # 保留原始分（调试）
        hits.append(card)

    return {
        "total": total,  # 各索引命中数之和（每文档全局唯一，并 = 和）
        "page": page,
        "size": size,
        "hits": hits,
    }


def search(p: dict[str, Any]) -> dict[str, Any]:
    type_ = p.get("type", "all")
    if type_ == "all":
        return _search_all(p)
    return _search_one(type_, p)


__all__ = ["search"]

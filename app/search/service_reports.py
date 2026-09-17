"""
报告检索 service。

词法 + 向量两路召回，RRF 融合排序；列表不带摘要，摘要在详情里单独取。
"""

from __future__ import annotations

# import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Mapping

from ..config import ENABLE_VECTOR_SEARCH, ES_SEARCH_WORKERS
from ..db import get_es
from .query_reports import (
    INDEX, build_detail_query, build_knn_query, build_query, window,
)
from .encoder import get_encoder
from .rank import LEXICAL, VECTOR, fuse, plain
from .response import hit_to_card_report

# _encoder = None
# _encoder_lock = threading.Lock()

TYPE = "report"

_search_pool = ThreadPoolExecutor(max_workers=ES_SEARCH_WORKERS, thread_name_prefix="es-report")


def _page_size(p: Mapping[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _query_vector(q: str) -> list[float]:
    return get_encoder().encode_query(q)


# def _get_encoder() -> Any:
#     global _encoder
#     with _encoder_lock:
#         if _encoder is None:
#             from embedding.encoder import Encoder
#             _encoder = Encoder()
#         return _encoder


def _run(body: dict[str, Any]) -> dict[str, Any]:
    return get_es().search(index=INDEX, **body)


def _pools(p: Mapping[str, Any], need: int, vector: list[float] | None
           ) -> tuple[list[tuple[str, str, list[dict[str, Any]]]], int]:
    """每一路给回一个有序命中列表，外加词法分支的命中总数。"""
    page_1 = {**p, "page": 1, "size": need}

    tasks: list[tuple[str, str, Any]] = [
        (TYPE, LEXICAL, _search_pool.submit(_run, build_query(page_1))),
    ]
    if vector is not None:
        tasks.append((TYPE, VECTOR, _search_pool.submit(
            _run, build_knn_query(page_1, vector))))

    pools: list[tuple[str, str, list[dict[str, Any]]]] = []
    total = 0
    for type_, retriever, future in tasks:
        res = future.result()
        pools.append((type_, retriever, res["hits"]["hits"]))
        if retriever == LEXICAL:
            total += res["hits"]["total"]["value"]

    return pools, total


def _card(ranked: Any) -> dict[str, Any]:
    card = hit_to_card_report(ranked.hit)
    card.pop("summary")                              # 摘要不进列表
    card["score"] = ranked.score                     # RRF 分
    card["raw_score"] = ranked.bm25                  # BM25，词法没命中时为 None
    card["knn_score"] = ranked.knn                   # ES cosine，值域是 (1 + cos) / 2
    card["match_source"] = ("both" if len(ranked.retrievers) > 1
                            else next(iter(ranked.retrievers)))
    return card


# def _detail(hit: Mapping[str, Any]) -> dict[str, Any]:
#     src = hit.get("_source") or {}
#     return {
#         "report_id": src.get("report_id") or hit.get("_id"),
#         "title": src.get("title"),
#         "summary": src.get("summary"),
#         "industry": src.get("industry") or [],
#         "layout": src.get("layout"),
#         "publish_date": src.get("publish_date"),
#         "url": src.get("url"),
#     }


def search(p: Mapping[str, Any]) -> dict[str, Any]:
    """
    Search for documents matching the query.
    """
    page, size = _page_size(p)
    q = p.get("q")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("q is required: reports search needs a query")

    need = window(p)
    vector = _query_vector(q.strip()) if ENABLE_VECTOR_SEARCH else None

    pools, total = _pools(p, need, vector)

    # A filter-only request has no relevance signal to fuse
    ranked = fuse(pools, page, size) if vector is not None else plain(pools, page, size)

    return {"total": total, "page": page, "size": size,
            "hits": [_card(f) for f in ranked]}


def get(report_id: str) -> dict[str, Any] | None:
    res = get_es().search(index=INDEX, **build_detail_query(report_id))
    hits = res["hits"]["hits"]
    return hit_to_card_report(hits[0]) if hits else None


__all__ = ["search", "get"]

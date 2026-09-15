from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import ENABLE_VECTOR_SEARCH, ES_SEARCH_WORKERS, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .fields import *
from .query import build_knn_query, build_query, window
from .rank import LEXICAL, VECTOR, fuse, plain
from .response import hit_to_card

_encoder = None
_encoder_lock = threading.Lock()

# Shared, not per request: a fixed pool bounds how many searches hit ES at once.
_search_pool = ThreadPoolExecutor(max_workers=ES_SEARCH_WORKERS, thread_name_prefix="es-search")


def _page_size(p: dict[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _applicable_types(p: dict[str, Any], base: tuple[str, ...] | list[str] = OBJECT_TYPES) -> set[str]:
    """
    Return applicable object types by intersecting the declared applicability
    of every filter present in ``p`` (see fields.FIELD_TYPES).

    """
    types = set(base)
    for key, allowed in FIELD_TYPES.items():
        if p.get(key):
            types &= set(allowed)
    return types


def _empty(total: int, p: dict[str, Any]) -> dict[str, Any]:
    page, size = _page_size(p)
    return {"total": total, "page": page, "size": size, "hits": []}


def _query_vector(q: str) -> list[float]:
    """
    Embed a search query.

    """
    return _get_encoder().encode_query(q)


def _get_encoder() -> Any:
    global _encoder
    with _encoder_lock:
        if _encoder is None:
            from embedding.encoder import Encoder
            _encoder = Encoder()
        return _encoder


def _run(index: str, body: dict[str, Any]) -> dict[str, Any]:
    return get_es().search(index=index, **body)


def _pools(active: list[str], p: dict[str, Any], need: int, vector: list[float] | None
           ) -> tuple[list[tuple[str, str, list[dict[str, Any]]]], int]:
    """
    Return a list of ranked lists for each active type, plus the match count.

    """
    page_1 = {**p, "page": 1, "size": need}

    tasks: list[tuple[str, str, Any]] = []
    for t in active:
        tasks.append((t, LEXICAL, _search_pool.submit(
            _run, INDEX_BY_TYPE[t], build_query(t, page_1))))
        if vector is not None:
            tasks.append((t, VECTOR, _search_pool.submit(
                _run, INDEX_BY_TYPE[t], build_knn_query(t, page_1, vector))))

    pools: list[tuple[str, str, list[dict[str, Any]]]] = []
    total = 0
    for type_, retriever, future in tasks:          # in submission order
        res = future.result()
        pools.append((type_, retriever, res["hits"]["hits"]))
        if retriever == LEXICAL:
            total += res["hits"]["total"]["value"]

    return pools, total


def _card(ranked: Any) -> dict[str, Any]:
    card = hit_to_card(ranked.hit, ranked.type)
    card["score"] = ranked.score                     # RRF score
    card["raw_score"] = ranked.bm25                  # BM25, None when the lexical branch missed
    card["knn_score"] = ranked.knn                   # ES cosine, reported as (1 + cos) / 2
    card["match_source"] = ("both" if len(ranked.retrievers) > 1
                            else next(iter(ranked.retrievers)))
    return card


def search(p: dict[str, Any]) -> dict[str, Any]:
    """
    Search for documents matching the query.

    """
    page, size = _page_size(p)
    type_ = p.get("type", "all")
    base = OBJECT_TYPES if type_ == "all" else (type_,)

    types = _applicable_types(p, base=base)
    if not types:
        return _empty(0, p)

    need = window(p)
    q = p.get("q")
    vector = _query_vector(q) if (q and ENABLE_VECTOR_SEARCH) else None
    active = [t for t in OBJECT_TYPES if t in types]

    pools, total = _pools(active, p, need, vector)

    # A filter-only request has no relevance signal to fuse
    ranked = fuse(pools, page, size) if q else plain(pools, page, size)

    return {"total": total, "page": page, "size": size,
            "hits": [_card(f) for f in ranked]}


__all__ = ["search"]

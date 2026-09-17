from __future__ import annotations

from typing import Any, Iterable, NamedTuple

from .fields import RRF_RANK_CONSTANT

# which branch a ranked list came from
LEXICAL = "bm25"
VECTOR = "knn"

# (object type, retriever, hits) -- hits are ES hits in ranked order
Pool = tuple[str, str, list[dict[str, Any]]]


class Fused(NamedTuple):
    score: float                      # RRF score
    best_rank: int                    # best rank across the lists it appeared in
    hit: dict[str, Any]
    type: str
    retrievers: frozenset[str]
    bm25: float | None
    knn: float | None


def _collect(pools: Iterable[Pool], k: int) -> dict[str, dict[str, Any]]:
    """
    Fold ranked lists into one entry per document.
    """
    by_id: dict[str, dict[str, Any]] = {}

    for type_, retriever, hits in pools:
        for position, hit in enumerate(hits, 1):
            doc_id = hit.get("_id")
            if doc_id is None:
                continue

            entry = by_id.get(doc_id)
            if entry is None:
                entry = {"score": 0.0, "best_rank": position, "hit": hit, "type": type_,
                         "retrievers": set(), "bm25": None, "knn": None}
                by_id[doc_id] = entry
            elif "_source" in hit and "_source" not in entry["hit"]:
                entry["hit"] = hit

            entry["score"] += 1.0 / (k + position)
            entry["best_rank"] = min(entry["best_rank"], position)
            entry["retrievers"].add(retriever)
            if retriever == LEXICAL and entry["bm25"] is None:
                entry["bm25"] = hit.get("_score")
            elif retriever == VECTOR and entry["knn"] is None:
                entry["knn"] = hit.get("_score")

    return by_id


def _order(entries: Iterable[dict[str, Any]], page: int, size: int) -> list[Fused]:
    """Sort and slice."""
    fused = [
        Fused(e["score"], e["best_rank"], e["hit"], e["type"],
              frozenset(e["retrievers"]), e["bm25"], e["knn"])
        for e in entries
    ]
    # third key is not decoration: equal RRF scores are common, so without it the
    # same query can put different documents on successive pages
    fused.sort(key=lambda f: (-f.score, f.best_rank, f.hit.get("_id") or ""))
    start = (page - 1) * size
    return fused[start:start + size]


def _constant(k: int | None = None) -> int:
    return RRF_RANK_CONSTANT if k is None else k


def fuse(pools: Iterable[Pool], page: int, size: int,
         k: int | None = None) -> list[Fused]:
    """Rank-fuse hits from different pools and return one page."""
    return _order(_collect(pools, _constant(k)).values(), page, size)


def plain(pools: Iterable[Pool], page: int, size: int) -> list[Fused]:
    """Ordering for a filter-only request, where no ranking signal exists."""
    flat = [
        Fused(0.0, position, hit, type_, frozenset({retriever}),
              hit.get("_score"), None)
        for type_, retriever, hits in pools
        for position, hit in enumerate(hits, 1)
    ]
    start = (page - 1) * size
    return flat[start:start + size]


__all__ = ["fuse", "plain", "Fused", "Pool", "LEXICAL", "VECTOR"]

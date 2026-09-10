from __future__ import annotations

from typing import Any

from ..config import INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .fields import *
from .query import build_query
from .rank import fuse
from .response import hit_to_card

def _page_size(p: dict[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def _applicable_types(p: dict[str, Any], base: tuple[str, ...] | list[str] = OBJECT_TYPES) -> set[str]:
    """
    Return applicable object types by intersecting the association filters.
    """
    types = set(base)
    if p.get("source_ids"):
        types &= set(ASSOC_SOURCE_IDS_TYPES)
    if p.get("evidence_ids"):
        types &= set(ASSOC_EVIDENCE_IDS_TYPES)
    if p.get("publisher"):
        types &= set(PUBLISHER_FIELD)
    return types


def _empty(total: int, p: dict[str, Any]) -> dict[str, Any]:
    page, size = _page_size(p)
    return {"total": total, "page": page, "size": size, "hits": []}


def _search_one(type_: str, p: dict[str, Any]) -> dict[str, Any]:
    if type_ not in _applicable_types(p, base=(type_,)):
        return _empty(0, p)
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
    need = page * size

    pools = []
    total = 0
    for t in OBJECT_TYPES:
        if t not in types:
            continue
        res = es.search(index=INDEX_BY_TYPE[t], **build_query(t, {**p, "page": 1, "size": need}))
        total += res["hits"]["total"]["value"]
        pools.append((t, res["hits"]["hits"], res["hits"].get("max_score")))

    hits = []
    for norm, raw, h, t in fuse(pools, page, size):
        card = hit_to_card(h, t)
        card["score"] = norm     # normalized score
        card["raw_score"] = raw  # BM25 score
        hits.append(card)

    return {"total": total, "page": page, "size": size, "hits": hits}


def search(p: dict[str, Any]) -> dict[str, Any]:
    type_ = p.get("type", "all")
    return _search_all(p) if type_ == "all" else _search_one(type_, p)


__all__ = ["search"]

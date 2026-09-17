"""
报告语义检索 service。

仅有语义检索 - 向量
"""

from __future__ import annotations

# import threading
from typing import Any, Mapping


from ..db import get_es
from .query_reports import INDEX, build_detail_query, build_knn_query
from .encoder import get_encoder
from .response import hit_to_card_report

# _encoder = None
# _encoder_lock = threading.Lock()


# def _get_encoder() -> Any:
#     global _encoder
#     with _encoder_lock:
#         if _encoder is None:
#             from embedding.encoder import Encoder
#             _encoder = Encoder()
#         return _encoder


def _card(hit: Mapping[str, Any]) -> dict[str, Any]:
    src = hit.get("_source") or {}
    return {
        "report_id": src.get("report_id") or hit.get("_id"),
        "title": src.get("title"),
        "industry": src.get("industry") or [],
        "layout": src.get("layout"),
        "publish_date": src.get("publish_date"),
        "url": src.get("url"),
        "score": hit.get("_score"),
    }


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
    q = p.get("q")
    if not isinstance(q, str) or not q.strip():
        raise ValueError("q is required: reports search is semantic-only")

    vector = get_encoder().encode_query(q.strip())
    res = get_es().search(index=INDEX, **build_knn_query(p, vector))

    return {"hits": [_card(h) for h in res["hits"]["hits"]]}


def get(report_id: str) -> dict[str, Any] | None:
    res = get_es().search(index=INDEX, **build_detail_query(report_id))
    hits = res["hits"]["hits"]
    return hit_to_card_report(hits[0]) if hits else None


__all__ = ["search", "get"]

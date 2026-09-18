"""
报告检索的查询构造。

"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

from . import time_decay

INDEX = "knowledge_report_index"

# --- 词法分支 ---
ANALYZER = "ik_smart"

REPORT_FIELDS: list[str] = ["title^3", "industry.text^2", "summary"]

MATCH_MODES = ("or", "and", "phrase")

SOURCE_FIELDS: list[str] = [
    "report_id", "title", "industry",
    "layout", "publish_date", "url",
]

DETAIL_FIELDS: list[str] = [*SOURCE_FIELDS, "summary"]

EMBED_FIELD = "embedding"

LAYOUTS = ("横版", "竖版")

KNN_NUM_CANDIDATES_FACTOR = 5

RESULT_WINDOW = 200

# DECAY_SCALE_DAYS = 365
# DECAY_OFFSET_DAYS = 90
DECAY_FIELD = "publish_date"


class WindowTooDeep(ValueError):
    """
    The requested page is past RESULT_WINDOW.
    """

def _page_size(p: Mapping[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def window(p: Mapping[str, Any]) -> int:
    """How many hits every retriever is asked for, or raise if the page is too deep."""
    page, size = _page_size(p)
    if page * size > RESULT_WINDOW:
        raise WindowTooDeep(
            f"page*size = {page * size} exceeds RESULT_WINDOW = {RESULT_WINDOW}; "
            f"fusion re-reads that many hits from every retriever to stay page-stable"
        )
    return RESULT_WINDOW

# def _decay_weight(p: Mapping[str, Any]) -> float:
#     return min(max(float(p.get("time_weight") or 0.0), 0.0), 1.0)

def _terms(field: str, values: Any) -> dict[str, Any]:
    vals = [str(v) for v in values] if isinstance(values, (list, tuple)) else [str(values)]
    return {"terms": {field: vals}}


def _date(value: Any) -> str:
    text = str(value)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"publish_date must be YYYY-MM-DD: {text!r}")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"publish_date is not a real date: {text!r}") from None
    return text


def build_filters(p: Mapping[str, Any]) -> list[dict[str, Any]]:
    f: list[dict[str, Any]] = []

    if p.get("report_id"):
        f.append(_terms("report_id", p["report_id"]))
    if p.get("layout"):
        f.append(_terms("layout", p["layout"]))
    if p.get("industry"):
        f.append(_terms("industry", p["industry"]))

    date_range: dict[str, Any] = {}
    if p.get("publish_date_from"):
        date_range["gte"] = _date(p["publish_date_from"])
    if p.get("publish_date_to"):
        date_range["lte"] = _date(p["publish_date_to"])
    if date_range:
        f.append({"range": {"publish_date": date_range}})

    return f


def _multi_match(q: str, mode: str = "or") -> dict[str, Any]:
    mm: dict[str, Any] = {
        "query": q,
        "analyzer": ANALYZER,
        "fields": REPORT_FIELDS,
        "type": "best_fields",
    }
    if mode == "and":
        mm["operator"] = "and"
    elif mode == "phrase":
        mm["type"] = "phrase"
    return {"multi_match": mm}


def build_query(p: Mapping[str, Any]) -> dict[str, Any]:
    """ return a dict for Elasticsearch query body."""
    mode = p.get("mode") or "or"
    if mode not in MATCH_MODES:
        raise ValueError(f"unknown mode: {mode!r} (expected one of {MATCH_MODES})")

    must: list[dict[str, Any]] = []
    q = p.get("q")
    if q:
        must.append(_multi_match(q, mode))

    filters = build_filters(p)

    query: dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters

    page, size = _page_size(p)
    window(p)

    body: dict[str, Any] = {
        "query": query,
        "source": SOURCE_FIELDS,
        "from_": (page - 1) * size,
        "size": size,
        "track_total_hits": True,
    }

    w = time_decay.weight(p)
    if w > 0.0:
        body["rescore"] = time_decay.rescore(DECAY_FIELD, w, size)

    if must and p.get("highlight", True) is not False:
        body["highlight"] = {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {f.split("^", 1)[0]: {} for f in REPORT_FIELDS},
            "highlight_query": {"bool": {"must": must}},
        }

    return body


def build_knn_query(p: Mapping[str, Any], vector: Sequence[float]) -> dict[str, Any]:
    need = window(p)

    knn: dict[str, Any] = {
        "field": EMBED_FIELD,
        "query_vector": list(vector),
        "k": need,
        "num_candidates": max(need * KNN_NUM_CANDIDATES_FACTOR, need + 10),
    }

    filters = build_filters(p)
    if filters:
        knn["filter"] = filters

    body: dict[str, Any] = {"knn": knn, "source": SOURCE_FIELDS, "size": need}

    w = time_decay.weight(p)
    if w > 0.0:
        body["rescore"] = time_decay.rescore(DECAY_FIELD, w, need)

    return body


def build_detail_query(report_id: str) -> dict[str, Any]:
    return {
        "query": {"term": {"report_id": report_id}},
        "source": DETAIL_FIELDS,
        "size": 1,
    }


__all__ = [
    "INDEX", "SOURCE_FIELDS", "DETAIL_FIELDS", "EMBED_FIELD", "LAYOUTS",
    "RESULT_WINDOW", "KNN_NUM_CANDIDATES_FACTOR", "MATCH_MODES", "DECAY_FIELD",
    "WindowTooDeep", "window", "build_filters", "build_query",
    "build_knn_query", "build_detail_query",
]

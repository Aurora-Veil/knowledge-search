"""
报告检索的查询构造。

"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping, Sequence

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

MAX_RESULT_WINDOW = 10000
KNN_NUM_CANDIDATES_FACTOR = 5


class WindowTooDeep(ValueError):
    """请求的页码超出 ES 的结果窗口。"""

def _page_size(p: Mapping[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def window(p: Mapping[str, Any]) -> int:
    page, size = _page_size(p)
    end = page * size
    if end > MAX_RESULT_WINDOW:
        raise WindowTooDeep(
            f"page*size = {end} exceeds MAX_RESULT_WINDOW = {MAX_RESULT_WINDOW}"
        )
    return end


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


# --- 词法分支 ---
#
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
#
#
# def build_query(p: Mapping[str, Any]) -> dict[str, Any]:
# 
#     mode = p.get("mode") or "or"
#     if mode not in MATCH_MODES:
#         raise ValueError(f"unknown mode: {mode!r} (expected one of {MATCH_MODES})")
#
#     must: list[dict[str, Any]] = []
#     q = p.get("q")
#     if q:
#         must.append(_multi_match(q, mode))
#
#     filters = build_filters(p)
#
#     query: dict[str, Any] = {"bool": {}}
#     if must:
#         query["bool"]["must"] = must
#     if filters:
#         query["bool"]["filter"] = filters

    # highlight = {
    #     "pre_tags": ["<em>"],
    #     "post_tags": ["</em>"],
    #     "fields": {f.split("^", 1)[0]: {} for f in REPORT_FIELDS},
    # }

#     page, size = _page_size(p)
#     window(p)
#
#     body: dict[str, Any] = {
#         "query": query,
#         "source": SOURCE_FIELDS,
#         "from_": (page - 1) * size,
#         "size": size,
#         "track_total_hits": True,
#     }
#
#     if must and p.get("highlight", True) is not False:
#         body["highlight"] = {
#             "pre_tags": ["<em>"],
#             "post_tags": ["</em>"],
#             "fields": {f.split("^", 1)[0]: {} for f in REPORT_FIELDS},
#             "highlight_query": {"bool": {"must": must}},
#         }
#
#     return body


def build_knn_query(p: Mapping[str, Any], vector: Sequence[float]) -> dict[str, Any]:
    end = window(p)
    page, size = _page_size(p)

    knn: dict[str, Any] = {
        "field": EMBED_FIELD,
        "query_vector": list(vector),
        "k": end,
        "num_candidates": min(max(end * KNN_NUM_CANDIDATES_FACTOR, end + 10),
                              MAX_RESULT_WINDOW),
    }

    filters = build_filters(p)
    if filters:
        knn["filter"] = filters

    body: dict[str, Any] = {"knn": knn, "source": SOURCE_FIELDS, "size": size}
    if page > 1:
        body["from_"] = end - size
    return body


def build_detail_query(report_id: str) -> dict[str, Any]:
    return {
        "query": {"term": {"report_id": report_id}},
        "source": DETAIL_FIELDS,
        "size": 1,
    }


__all__ = [
    "INDEX", "SOURCE_FIELDS", "DETAIL_FIELDS", "EMBED_FIELD", "LAYOUTS",
    "MAX_RESULT_WINDOW", "KNN_NUM_CANDIDATES_FACTOR",
    "WindowTooDeep", "window", "build_filters", "build_knn_query",
    "build_detail_query",
]

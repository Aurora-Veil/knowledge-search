"""报告库的全局统计：只走 ES 聚合，不取文档。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import get_es
from .query_reports import INDEX

MAX_INDUSTRIES = 10
MAX_LAYOUTS = 10

_AGGS = {
    "years": {
        "date_histogram": {
            "field": "publish_date",
            "calendar_interval": "year",
            "format": "yyyy",
            "min_doc_count": 0,
        }
    },
    "industries": {"terms": {"field": "industry", "size": MAX_INDUSTRIES}},
    "industry_total": {"cardinality": {"field": "industry"}},
    "layouts": {"terms": {"field": "layout", "size": MAX_LAYOUTS}},
    "publish_min": {"min": {"field": "publish_date", "format": "yyyy-MM-dd"}},
    "publish_max": {"max": {"field": "publish_date", "format": "yyyy-MM-dd"}},
}


def overview() -> dict[str, Any]:
    res = get_es().search(index=INDEX, size=0, track_total_hits=True, aggs=_AGGS)
    aggs = res["aggregations"]

    return {
        "total": int(res["hits"]["total"]["value"]),
        "years": [
            {"year": int(b["key_as_string"]), "count": b["doc_count"]}
            for b in aggs["years"]["buckets"]
        ],
        "industries": [
            {"name": b["key"], "count": b["doc_count"]}
            for b in aggs["industries"]["buckets"]
        ],
        "industry_count": int(aggs["industry_total"]["value"]),
        "layouts": [
            {"name": b["key"], "count": b["doc_count"]}
            for b in aggs["layouts"]["buckets"]
        ],
        "publish_range": {
            "from": aggs["publish_min"].get("value_as_string"),
            "to": aggs["publish_max"].get("value_as_string"),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

"""报告库的全局统计：只走 ES 聚合，不取文档。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..db import get_es
from .query_reports import INDEX

MAX_INDUSTRIES = 10
MAX_LAYOUTS = 10

_YEAR_HISTOGRAM = {
    "date_histogram": {
        "field": "publish_date",
        "calendar_interval": "year",
        "format": "yyyy",
        "min_doc_count": 0,
    }
}

_AGGS = {
    "years": {
        **_YEAR_HISTOGRAM,
        "aggs": {
            "industries": {"terms": {"field": "industry", "size": MAX_INDUSTRIES}},
            "industry_total": {"cardinality": {"field": "industry"}},
        },
    },
    "industries": {
        "terms": {"field": "industry", "size": MAX_INDUSTRIES},
    },
    "industry_total": {"cardinality": {"field": "industry"}},
    "layouts": {"terms": {"field": "layout", "size": MAX_LAYOUTS}},
    "publish_min": {"min": {"field": "publish_date", "format": "yyyy-MM-dd"}},
    "publish_max": {"max": {"field": "publish_date", "format": "yyyy-MM-dd"}},
}


def _industry_years(names: list[str]) -> dict[str, dict[str, Any]]:
    if not names:
        return {}

    res = get_es().search(
        index=INDEX,
        size=0,
        query={"terms": {"industry": names}},
        aggs={
            "industries": {
                "terms": {"field": "industry", "size": len(names)},
                "aggs": {"years": _YEAR_HISTOGRAM},
            }
        },
    )

    return {
        bucket["key"]: {
            "count": bucket["doc_count"],
            "years": [
                {"year": int(item["key_as_string"]), "count": item["doc_count"]}
                for item in bucket["years"]["buckets"]
            ],
        }
        for bucket in res["aggregations"]["industries"]["buckets"]
    }


def overview() -> dict[str, Any]:
    res = get_es().search(index=INDEX, size=0, track_total_hits=True, aggs=_AGGS)
    aggs = res["aggregations"]

    years = []
    for bucket in aggs["years"]["buckets"]:
        years.append({
            "year": int(bucket["key_as_string"]),
            "count": bucket["doc_count"],
            "industry_total": int(bucket["industry_total"]["value"]),
            "industries": [
                {"name": item["key"], "count": item["doc_count"]}
                for item in bucket["industries"]["buckets"]
            ],
        })

    industries = [
        {"name": bucket["key"], "count": bucket["doc_count"]}
        for bucket in aggs["industries"]["buckets"]
    ]

    # 年份图里出现的行业也要能反查年份，否则只能联动全局 Top 10 的行业
    names = {item["name"] for item in industries}
    for year in years:
        names.update(item["name"] for item in year["industries"])
    industry_years = _industry_years(sorted(names))

    for item in industries:
        item["years"] = industry_years.get(item["name"], {}).get("years", [])

    return {
        "total": int(res["hits"]["total"]["value"]),
        "years": years,
        "industries": industries,
        "industry_years": industry_years,
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

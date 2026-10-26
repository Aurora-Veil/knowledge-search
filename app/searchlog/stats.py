"""search_log 的只读聚合：只出统计值，不暴露单条请求。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from ..db import get_pg

MAX_SPAN_DAYS = 366
MAX_TOP_QUERIES = 20
MAX_QUERIES = 20

DEFAULT_DAYS = 14
DEFAULT_LIMIT = 5

_CONNECT_TIMEOUT = 2.0

UNAVAILABLE = (psycopg.OperationalError, RuntimeError)

Granularity = Literal["day", "week", "month"]

_FILTER = """
    WHERE page = 1
      AND (created_at AT TIME ZONE 'Asia/Shanghai')::date BETWEEN %(start)s AND %(end)s
      AND (%(kind)s::text IS NULL OR kind = %(kind)s)
      AND (%(only_me)s::boolean = false OR user_id = %(user_id)s)
"""

# 不带 CTE 和日期序列：直接 group by 才能走并行顺序扫描。
# 空桶在 Python 里补，日期序列放在 SQL 里会让计划退回单进程。
_DAILY = f"""
SELECT date_trunc(%(granularity)s::text,
                  (created_at AT TIME ZONE 'Asia/Shanghai')::timestamp)::date AS bucket,
       count(*) AS searches,
       count(*) FILTER (WHERE outcome = 'ok' AND result_total = 0) AS zero_result,
       count(*) FILTER (WHERE outcome = 'error') AS errors,
       sum(latency_ms) FILTER (WHERE outcome = 'ok') AS latency_sum,
       count(*) FILTER (WHERE outcome = 'ok') AS ok_count
FROM search_log
{_FILTER}
  AND (%(queries)s::text[] IS NULL OR query = ANY(%(queries)s))
GROUP BY 1
ORDER BY 1
"""

_TOP = f"""
SELECT query, count(*) AS count
FROM search_log
{_FILTER}
GROUP BY query
ORDER BY count DESC, query ASC
LIMIT %(limit)s
"""

_SELECTED = f"""
SELECT query, count(*) AS count
FROM search_log
{_FILTER}
  AND query = ANY(%(queries)s)
GROUP BY query
"""

_TODAY = "SELECT (now() AT TIME ZONE 'Asia/Shanghai')::date AS today"


def _bucket_start(day: date, granularity: Granularity) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def _next_bucket(day: date, granularity: Granularity) -> date:
    if granularity == "week":
        return day + timedelta(days=7)
    if granularity == "month":
        if day.month == 12:
            return day.replace(year=day.year + 1, month=1)
        return day.replace(month=day.month + 1)
    return day + timedelta(days=1)


def _normalize_queries(queries: list[str] | None) -> list[str]:
    picked = [item.strip() for item in (queries or []) if item.strip()]
    picked = list(dict.fromkeys(picked))
    if len(picked) > MAX_QUERIES:
        raise ValueError(f"queries: at most {MAX_QUERIES} items")
    return picked


def overview(user_id: int | None, days: int = DEFAULT_DAYS,
             start: date | None = None, end: date | None = None,
             queries: list[str] | None = None, scope: Literal["all", "me"] = "all",
             kind: Literal["oirf", "report"] | None = None,
             granularity: Granularity = "day",
             limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    if scope == "me" and user_id is None:
        raise ValueError("scope=me needs a user_id")
    if days < 1:
        raise ValueError("days must be >= 1")
    if granularity not in ("day", "week", "month"):
        raise ValueError("granularity must be day, week or month")

    queries = _normalize_queries(queries)
    limit = max(1, min(limit, MAX_TOP_QUERIES))

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_TODAY)
            today = cur.fetchone()["today"]

            end = end or today
            start = start or end - timedelta(days=days - 1)

            if start > end:
                raise ValueError("start must be <= end")
            if (end - start).days + 1 > MAX_SPAN_DAYS:
                raise ValueError(f"span: at most {MAX_SPAN_DAYS} days")

            params = {
                "start": start,
                "end": end,
                "granularity": granularity,
                "queries": queries or None,
                "kind": kind,
                "only_me": scope == "me",
                "user_id": user_id,
                "limit": limit,
            }

            cur.execute(_DAILY, params)
            rows = cur.fetchall()
            cur.execute(_TOP, params)
            top = cur.fetchall()

            selected: dict[str, int] = {}
            if queries:
                cur.execute(_SELECTED, params)
                selected = {row["query"]: int(row["count"]) for row in cur.fetchall()}

    by_bucket = {row["bucket"]: row for row in rows}
    buckets: list[dict[str, Any]] = []
    cursor = _bucket_start(start, granularity)
    while cursor <= end:
        row = by_bucket.get(cursor)
        buckets.append({
            "date": cursor.isoformat(),
            "searches": int(row["searches"]) if row else 0,
            "zero_result": int(row["zero_result"]) if row else 0,
            "errors": int(row["errors"]) if row else 0,
        })
        cursor = _next_bucket(cursor, granularity)

    searches = sum(item["searches"] for item in buckets)
    zero_result = sum(item["zero_result"] for item in buckets)
    latency_sum = sum(int(row["latency_sum"]) for row in rows)
    ok_count = sum(int(row["ok_count"]) for row in rows)

    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "granularity": granularity,
        },
        "daily": buckets,
        "top_queries": [
            {"query": row["query"], "count": int(row["count"])}
            for row in top
        ],
        "selected": [
            {"query": query, "count": selected.get(query, 0)}
            for query in queries
        ],
        "totals": {
            "searches": searches,
            "zero_result_rate": round(zero_result / searches, 4) if searches else 0.0,
            "avg_latency_ms": int(round(latency_sum / ok_count)) if ok_count else 0,
        },
    }

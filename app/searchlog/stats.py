"""search_daily 的只读聚合：只出统计值，不读 search_log。

仪表只能查这张汇总表 —— 任何参数组合都不会落到 search_log 上。
汇总表由 app/searchlog/rollup.py 每天凌晨维护，口径见那里。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from ..db import get_pg

MAX_SPAN_DAYS = 366
MAX_TOP_QUERIES = 20
MAX_QUERIES = 20

DEFAULT_DAYS = 14
DEFAULT_LIMIT = 5

_CONNECT_TIMEOUT = 2.0

TZ = ZoneInfo("Asia/Shanghai")

UNAVAILABLE = (psycopg.Error, RuntimeError)

Granularity = Literal["day", "week", "month"]

_FILTER = """
    WHERE day BETWEEN %(start)s AND %(end)s
      AND (%(kind)s::text IS NULL OR kind = %(kind)s)
"""

_DAILY = f"""
SELECT date_trunc(%(granularity)s::text, day::timestamp)::date AS bucket,
       sum(searches)::bigint    AS searches,
       sum(zero_result)::bigint AS zero_result,
       sum(errors)::bigint      AS errors,
       sum(latency_sum)::bigint AS latency_sum,
       sum(ok_count)::bigint    AS ok_count
FROM search_daily
{_FILTER}
  AND (%(queries)s::text[] IS NULL OR query = ANY(%(queries)s))
GROUP BY 1
ORDER BY 1
"""

_TOP = f"""
SELECT query, sum(searches)::bigint AS count
FROM search_daily
{_FILTER}
GROUP BY query
ORDER BY count DESC, query ASC
LIMIT %(limit)s
"""

_SELECTED = f"""
SELECT query, sum(searches)::bigint AS count
FROM search_daily
{_FILTER}
  AND query = ANY(%(queries)s)
GROUP BY query
"""

_DATA_UNTIL = "SELECT max(day) AS day FROM search_daily"


def today() -> date:
    return datetime.now(TZ).date()


def resolve_range(days: int, start: date | None, end: date | None,
                  *, now: date | None = None) -> tuple[date, date]:
    """解析并校验日期区间。路由层先调它，缓存键才用得上解析后的区间。"""
    if days < 1:
        raise ValueError("days must be >= 1")

    end = end or now or today()
    start = start or end - timedelta(days=days - 1)

    if start > end:
        raise ValueError("start must be <= end")
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise ValueError(f"span: at most {MAX_SPAN_DAYS} days")
    return start, end


def normalize_queries(queries: list[str] | None) -> list[str]:
    picked = [item.strip() for item in (queries or []) if item.strip()]
    picked = list(dict.fromkeys(picked))
    if len(picked) > MAX_QUERIES:
        raise ValueError(f"queries: at most {MAX_QUERIES} items")
    return picked


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


def overview(days: int = DEFAULT_DAYS,
             start: date | None = None, end: date | None = None,
             queries: list[str] | None = None,
             kind: Literal["oirf", "report"] | None = None,
             granularity: Granularity = "day",
             limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    if granularity not in ("day", "week", "month"):
        raise ValueError("granularity must be day, week or month")

    queries = normalize_queries(queries)
    limit = max(1, min(limit, MAX_TOP_QUERIES))

    now = today()
    start, end = resolve_range(days, start, end, now=now)

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DATA_UNTIL)
            data_until = cur.fetchone()["day"]

            # 今天的数据还没汇总，末端截到汇总表最新的那一天。
            stop = min(end, data_until) if data_until else None
            in_range = stop is not None and stop >= start

            rows: list[dict[str, Any]] = []
            top: list[dict[str, Any]] = []
            selected: dict[str, int] = {}

            if in_range:
                params = {
                    "start": start,
                    "end": stop,
                    "granularity": granularity,
                    "queries": queries or None,
                    "kind": kind,
                    "limit": limit,
                }

                cur.execute(_DAILY, params)
                rows = cur.fetchall()
                cur.execute(_TOP, params)
                top = cur.fetchall()

                if queries:
                    cur.execute(_SELECTED, params)
                    selected = {row["query"]: int(row["count"]) for row in cur.fetchall()}

    by_bucket = {row["bucket"]: row for row in rows}
    buckets: list[dict[str, Any]] = []
    cursor = _bucket_start(start, granularity)
    while in_range and cursor <= stop:
        row = by_bucket.get(cursor)
        buckets.append({
            "date": cursor.isoformat(),
            "searches": int(row["searches"]) if row else 0,
            "zero_result": int(row["zero_result"]) if row else 0,
            "errors": int(row["errors"]) if row else 0,
            "latency_sum": int(row["latency_sum"]) if row else 0,
            "ok_count": int(row["ok_count"]) if row else 0,
        })
        cursor = _next_bucket(cursor, granularity)

    searches = sum(int(row["searches"]) for row in rows)
    zero_result = sum(int(row["zero_result"]) for row in rows)
    errors = sum(int(row["errors"]) for row in rows)
    latency_sum = sum(int(row["latency_sum"]) for row in rows)
    ok_count = sum(int(row["ok_count"]) for row in rows)

    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "granularity": granularity,
        },
        "data_until": data_until.isoformat() if data_until else None,
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
            "zero_result": zero_result,
            "errors": errors,
            "zero_result_rate": round(zero_result / searches, 4) if searches else 0.0,
            "latency_sum": latency_sum,
            "ok_count": ok_count,
            "avg_latency_ms": int(round(latency_sum / ok_count)) if ok_count else 0,
        },
    }

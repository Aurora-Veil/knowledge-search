"""search_log 的只读聚合：只出统计值，不暴露单条请求。"""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from ..db import get_pg

MAX_TOP_QUERIES = 5

_CONNECT_TIMEOUT = 2.0

UNAVAILABLE = (psycopg.OperationalError, RuntimeError)

# 先聚合再和日期序列 join：直接 join 原始行会把百万级数据拖进 join，
# 聚合后只有 days 行。latency_sum / ok_count 只为算全局平均，不返回。
_DAILY = """
WITH days AS (
    SELECT generate_series(
               (now() AT TIME ZONE 'Asia/Shanghai')::date - (%(days)s::int - 1),
               (now() AT TIME ZONE 'Asia/Shanghai')::date,
               interval '1 day'
           )::date AS day
),
buckets AS (
    SELECT (created_at AT TIME ZONE 'Asia/Shanghai')::date AS day,
           count(*) AS searches,
           count(*) FILTER (WHERE outcome = 'ok' AND result_total = 0) AS zero_result,
           count(*) FILTER (WHERE outcome = 'error') AS errors,
           sum(latency_ms) FILTER (WHERE outcome = 'ok') AS latency_sum,
           count(*) FILTER (WHERE outcome = 'ok') AS ok_count
    FROM search_log
    WHERE page = 1
      AND (%(kind)s::text IS NULL OR kind = %(kind)s)
      AND (created_at AT TIME ZONE 'Asia/Shanghai')::date
          >= (now() AT TIME ZONE 'Asia/Shanghai')::date - (%(days)s::int - 1)
      AND (%(only_me)s::boolean = false OR user_id = %(user_id)s)
    GROUP BY 1
)
SELECT d.day,
       coalesce(b.searches, 0) AS searches,
       coalesce(b.zero_result, 0) AS zero_result,
       coalesce(b.errors, 0) AS errors,
       coalesce(b.latency_sum, 0) AS latency_sum,
       coalesce(b.ok_count, 0) AS ok_count
FROM days d
LEFT JOIN buckets b ON b.day = d.day
ORDER BY d.day
"""

_TOP = """
SELECT query, count(*) AS count
FROM search_log
WHERE page = 1
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
  AND (created_at AT TIME ZONE 'Asia/Shanghai')::date
      >= (now() AT TIME ZONE 'Asia/Shanghai')::date - (%(days)s::int - 1)
  AND (%(only_me)s::boolean = false OR user_id = %(user_id)s)
GROUP BY query
ORDER BY count DESC, query ASC
LIMIT %(limit)s
"""


def overview(user_id: int | None, days: int, scope: Literal["all", "me"],
             kind: Literal["oirf", "report"] | None = None) -> dict[str, Any]:
    if scope == "me" and user_id is None:
        raise ValueError("scope=me needs a user_id")

    params = {
        "days": days,
        "only_me": scope == "me",
        "user_id": user_id,
        "kind": kind,
        "limit": MAX_TOP_QUERIES,
    }

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DAILY, params)
            daily = cur.fetchall()
            cur.execute(_TOP, params)
            top = cur.fetchall()

    searches = sum(int(row["searches"]) for row in daily)
    zero_result = sum(int(row["zero_result"]) for row in daily)
    latency_sum = sum(int(row["latency_sum"]) for row in daily)
    ok_count = sum(int(row["ok_count"]) for row in daily)

    return {
        "days": days,
        "daily": [
            {
                "date": row["day"].isoformat(),
                "searches": int(row["searches"]),
                "zero_result": int(row["zero_result"]),
                "errors": int(row["errors"]),
            }
            for row in daily
        ],
        "top_queries": [
            {"query": row["query"], "count": int(row["count"])}
            for row in top
        ],
        "totals": {
            "searches": searches,
            "zero_result_rate": round(zero_result / searches, 4) if searches else 0.0,
            "avg_latency_ms": int(round(latency_sum / ok_count)) if ok_count else 0,
        },
    }

"""search_log 的只读聚合：只出统计值，不暴露单条请求。"""
from __future__ import annotations

from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from ..db import get_pg

MAX_TOP_QUERIES = 5

_CONNECT_TIMEOUT = 2.0

UNAVAILABLE = (psycopg.OperationalError, RuntimeError)

_DAILY = """
WITH days AS (
    SELECT generate_series(
               (now() AT TIME ZONE 'Asia/Shanghai')::date - (%(days)s::int - 1),
               (now() AT TIME ZONE 'Asia/Shanghai')::date,
               interval '1 day'
           )::date AS day
)
SELECT d.day,
       count(l.id) AS searches,
       count(l.id) FILTER (WHERE l.outcome = 'ok' AND l.result_total = 0) AS zero_result,
       count(l.id) FILTER (WHERE l.outcome = 'error') AS errors
FROM days d
LEFT JOIN search_log l
       ON (l.created_at AT TIME ZONE 'Asia/Shanghai')::date = d.day
      AND l.page = 1
      AND (%(kind)s::text IS NULL OR l.kind = %(kind)s)
      AND (%(only_me)s::boolean = false OR l.user_id = %(user_id)s)
GROUP BY d.day
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

_TOTALS = """
SELECT count(*) AS searches,
       count(*) FILTER (WHERE outcome = 'ok' AND result_total = 0) AS zero_result,
       avg(latency_ms) FILTER (WHERE outcome = 'ok') AS avg_latency_ms
FROM search_log
WHERE page = 1
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
  AND (created_at AT TIME ZONE 'Asia/Shanghai')::date
      >= (now() AT TIME ZONE 'Asia/Shanghai')::date - (%(days)s::int - 1)
  AND (%(only_me)s::boolean = false OR user_id = %(user_id)s)
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
            cur.execute(_TOTALS, params)
            totals = cur.fetchone()

    searches = int(totals["searches"] or 0)
    zero_result = int(totals["zero_result"] or 0)

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
            "avg_latency_ms": int(round(totals["avg_latency_ms"] or 0)),
        },
    }

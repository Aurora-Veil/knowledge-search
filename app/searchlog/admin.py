"""搜索日志：明细读 search_log，汇总只读四张按天的小表。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row

from ..db import get_pg
from . import stats as daily_stats

UNAVAILABLE = (psycopg.Error, RuntimeError)

TZ = ZoneInfo("Asia/Shanghai")

DEFAULT_DAYS = 7
MAX_SPAN_DAYS = 30
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

MAX_TOP_ERRORS = 10
MAX_TOP_USERS = 5

_BUCKET_MS = 50
_BUCKET_MAX_MS = 1000

_CONNECT_TIMEOUT = 2.0

_DETAIL = """
SELECT l.id, l.request_id, l.user_id, u.username,
       l.kind, l.query, l.filters, l.page, l.size,
       l.outcome, l.status_code, l.error_type, l.result_total,
       l.latency_ms, l.created_at
FROM search_log l
LEFT JOIN users u ON u.id = l.user_id
WHERE l.created_at >= %(start)s
  AND l.created_at <  %(end)s
  AND (%(kind)s::text IS NULL OR l.kind = %(kind)s)
  AND (%(outcome)s::text IS NULL OR l.outcome = %(outcome)s)
  AND (%(user_id)s::bigint IS NULL OR l.user_id = %(user_id)s)
  AND (%(cursor_ts)s::timestamptz IS NULL
       OR (l.created_at, l.id) < (%(cursor_ts)s, %(cursor_id)s))
ORDER BY l.created_at DESC, l.id DESC
LIMIT %(limit)s
"""

# search_daily 和 search_user_daily 列相同，靠下面两个常量选表，不接受外部输入。
_COUNTS_ALL = """
SELECT kind,
       sum(searches)::bigint    AS searches,
       sum(zero_result)::bigint AS zero_result,
       sum(errors)::bigint      AS errors,
       sum(latency_sum)::bigint AS latency_sum,
       sum(ok_count)::bigint    AS ok_count
FROM search_daily
WHERE day BETWEEN %(start)s AND %(end)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
GROUP BY kind
ORDER BY kind
"""

_COUNTS_USER = """
SELECT kind,
       sum(searches)::bigint    AS searches,
       sum(zero_result)::bigint AS zero_result,
       sum(errors)::bigint      AS errors,
       sum(latency_sum)::bigint AS latency_sum,
       sum(ok_count)::bigint    AS ok_count
FROM search_user_daily
WHERE day BETWEEN %(start)s AND %(end)s
  AND user_id = %(user_id)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
GROUP BY kind
ORDER BY kind
"""

_LATENCY = """
SELECT bucket, sum(count)::bigint AS count
FROM search_latency_daily
WHERE day BETWEEN %(start)s AND %(end)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
GROUP BY bucket
ORDER BY bucket
"""

_TOP_ERRORS = """
SELECT error_type, sum(count)::bigint AS count
FROM search_error_daily
WHERE day BETWEEN %(start)s AND %(end)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
GROUP BY error_type
ORDER BY count DESC, error_type ASC
LIMIT %(limit)s
"""

_DATA_UNTIL = "SELECT max(day) AS day FROM search_daily"

# search_user_daily 只有 user_id，用户名要回 users 表取；账号被删时 username 为空。
_TOP_USERS = """
SELECT d.user_id,
       u.username,
       sum(d.searches)::bigint AS searches
FROM search_user_daily d
LEFT JOIN users u ON u.id = d.user_id
WHERE d.day BETWEEN %(start)s AND %(end)s
  AND (%(kind)s::text IS NULL OR d.kind = %(kind)s)
GROUP BY d.user_id, u.username
ORDER BY searches DESC, d.user_id ASC
LIMIT %(user_limit)s
"""


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """自然日区间 [start, end] 转成半开的时间窗。"""
    return (
        datetime.combine(start, time.min, tzinfo=TZ),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=TZ),
    )


def _cursor(raw: str) -> tuple[datetime, int]:
    stamp, sep, ident = raw.rpartition("|")
    if not sep:
        raise ValueError("invalid cursor")
    try:
        return datetime.fromisoformat(stamp), int(ident)
    except ValueError as exc:
        raise ValueError("invalid cursor") from exc


def _percentile(buckets: list[dict[str, Any]], share: float) -> int | None:
    total = sum(int(row["count"]) for row in buckets)
    if not total:
        return None
    rank = share * total
    seen = 0
    for row in buckets:
        seen += int(row["count"])
        if seen >= rank:
            return min(int(row["bucket"]) * _BUCKET_MS, _BUCKET_MAX_MS)
    return _BUCKET_MAX_MS


def _rate(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


def list_logs(*, days: int = DEFAULT_DAYS,
              start: date | None = None, end: date | None = None,
              kind: Literal["oirf", "report"] | None = None,
              outcome: Literal["ok", "error"] | None = None,
              user_id: int | None = None,
              cursor: str | None = None,
              limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    """倒序，keyset 翻页。next 是上一页最后一条的游标，没有更多时为 null。"""
    start_day, end_day = daily_stats.resolve_range(
        days, start, end, max_span=MAX_SPAN_DAYS
    )
    low, high = _bounds(start_day, end_day)
    cursor_ts, cursor_id = _cursor(cursor) if cursor else (None, None)

    params = {
        "start": low,
        "end": high,
        "kind": kind,
        "outcome": outcome,
        "user_id": user_id,
        "cursor_ts": cursor_ts,
        "cursor_id": cursor_id,
        "limit": min(limit, MAX_LIMIT) + 1,
    }

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DETAIL, params)
            rows = cur.fetchall()

    more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if more:
        last = items[-1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['id']}"

    return {"items": items, "next": next_cursor}


def summary(*, days: int = DEFAULT_DAYS,
            start: date | None = None, end: date | None = None,
            kind: Literal["oirf", "report"] | None = None,
            user_id: int | None = None) -> dict[str, Any]:
    """只读按天的小表，不碰 search_log。今天还没汇总，末端截到 data_until。"""
    start_day, end_day = daily_stats.resolve_range(
        days, start, end, max_span=MAX_SPAN_DAYS
    )

    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_DATA_UNTIL)
            data_until = cur.fetchone()["day"]

            stop = min(end_day, data_until) if data_until else None
            in_range = stop is not None and stop >= start_day

            counts: list[dict[str, Any]] = []
            buckets: list[dict[str, Any]] = []
            top_errors: list[dict[str, Any]] = []
            top_users: list[dict[str, Any]] = []

            if in_range:
                params = {
                    "start": start_day,
                    "end": stop,
                    "kind": kind,
                    "user_id": user_id,
                    "limit": MAX_TOP_ERRORS,
                    "user_limit": MAX_TOP_USERS,
                }
                cur.execute(_COUNTS_USER if user_id else _COUNTS_ALL, params)
                counts = cur.fetchall()

                if user_id is None:
                    cur.execute(_LATENCY, params)
                    buckets = cur.fetchall()
                    cur.execute(_TOP_ERRORS, params)
                    top_errors = cur.fetchall()
                    cur.execute(_TOP_USERS, params)
                    top_users = cur.fetchall()

    searches = sum(int(row["searches"]) for row in counts)
    zero_result = sum(int(row["zero_result"]) for row in counts)
    errors = sum(int(row["errors"]) for row in counts)
    latency_sum = sum(int(row["latency_sum"]) for row in counts)
    ok_count = sum(int(row["ok_count"]) for row in counts)

    return {
        "range": {
            "start": start_day.isoformat(),
            "end": (stop or start_day).isoformat(),
            "requested_end": end_day.isoformat(),
        },
        "data_until": data_until.isoformat() if data_until else None,
        "user_id": user_id,
        "searches": searches,
        "zero_result": zero_result,
        "errors": errors,
        "error_rate": _rate(errors, searches),
        "zero_result_rate": _rate(zero_result, searches),
        "avg_latency_ms": int(round(latency_sum / ok_count)) if ok_count else 0,
        "latency_ms": {
            "p50": _percentile(buckets, 0.50),
            "p95": _percentile(buckets, 0.95),
            "p99": _percentile(buckets, 0.99),
        },
        "by_kind": [
            {
                "kind": row["kind"],
                "searches": int(row["searches"]),
                "errors": int(row["errors"]),
                "zero_result": int(row["zero_result"]),
                "error_rate": _rate(int(row["errors"]), int(row["searches"])),
                "zero_result_rate": _rate(int(row["zero_result"]), int(row["searches"])),
                "avg_latency_ms": (
                    int(round(int(row["latency_sum"]) / int(row["ok_count"])))
                    if int(row["ok_count"]) else 0
                ),
            }
            for row in counts
        ],
        "top_errors": [
            {"error_type": row["error_type"], "count": int(row["count"])}
            for row in top_errors
        ],
        "top_users": [
            {
                "user_id": row["user_id"],
                "username": row["username"],
                "searches": int(row["searches"]),
            }
            for row in top_users
        ],
    }

"""把 search_log 折叠成 search_daily。"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..db import get_pg

log = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")

MAX_QUERY_CHARS = 500

_CONNECT_TIMEOUT = 5.0

_DELETE = "DELETE FROM search_daily WHERE day = %(day)s"

_AGGREGATE = """
WITH src AS (
    SELECT kind,
           left(query, %(chars)s) AS query,
           outcome,
           result_total,
           latency_ms
    FROM search_log
    WHERE page = 1
      AND created_at >= (%(day)s::date::timestamp AT TIME ZONE 'Asia/Shanghai')
      AND created_at <  ((%(day)s::date + 1)::timestamp AT TIME ZONE 'Asia/Shanghai')
)
INSERT INTO search_daily
       (day, kind, query, searches, zero_result, errors, latency_sum, ok_count)
SELECT %(day)s::date,
       kind,
       query,
       count(*),
       count(*) FILTER (WHERE outcome = 'ok' AND result_total = 0),
       count(*) FILTER (WHERE outcome = 'error'),
       coalesce(sum(latency_ms) FILTER (WHERE outcome = 'ok'), 0),
       count(*) FILTER (WHERE outcome = 'ok')
FROM src
GROUP BY kind, query
"""

_FIRST_LOG_DAY = """
SELECT min((created_at AT TIME ZONE 'Asia/Shanghai')::date) AS day
FROM search_log
"""


def today() -> date:
    return datetime.now(TZ).date()


def first_log_day() -> date | None:
    """search_log 里最早的那个自然日；空表返回 None。"""
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        row = conn.execute(_FIRST_LOG_DAY).fetchone()
    return row[0] if row else None


def rebuild(day: date) -> int:
    """重算一天：先删后插，同一个事务。幂等。返回写入的行数。"""
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor() as cur:
            cur.execute(_DELETE, {"day": day})
            cur.execute(_AGGREGATE, {"day": day, "chars": MAX_QUERY_CHARS})
            return cur.rowcount


def rebuild_range(start: date, end: date) -> int:
    """逐天重算，每天一个事务：某一天失败不影响已经写完的其它天。"""
    if start > end:
        raise ValueError("start must be <= end")

    total = 0
    cursor = start
    while cursor <= end:
        written = rebuild(cursor)
        total += written
        log.info("search_daily %s: %d rows", cursor, written)
        cursor += timedelta(days=1)
    return total


def main(argv: list[str] | None = None) -> int:
    now = today()
    yesterday = now - timedelta(days=1)

    parser = argparse.ArgumentParser(
        prog="python -m app.searchlog.rollup",
        description="把 search_log 折叠成 search_daily",
    )
    parser.add_argument("--date", type=date.fromisoformat, help="只重算这一天")
    parser.add_argument("--from", dest="start", type=date.fromisoformat,
                        help="起始日，含；配合 --to")
    parser.add_argument("--to", dest="end", type=date.fromisoformat,
                        help="结束日，含；不写就是昨天")
    parser.add_argument("--days", type=int, help="重算最近 N 天，到昨天")
    parser.add_argument("--backfill", action="store_true",
                        help="从最早的日志日重算到昨天")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.date is not None:
        start = end = args.date
    elif args.backfill:
        first = first_log_day()
        if first is None:
            log.info("search_log 是空的，没有可汇总的数据")
            return 0
        if first > yesterday:
            log.info("search_log 里只有今天的数据，还没有完整的日期")
            return 0
        start, end = first, yesterday
    elif args.days is not None:
        if args.days < 1:
            log.error("--days 至少是 1")
            return 2
        end = yesterday
        start = end - timedelta(days=args.days - 1)
    elif args.start is not None or args.end is not None:
        end = args.end or yesterday
        start = args.start or end
    else:
        start, end = now - timedelta(days=2), yesterday

    if start > end:
        log.error("起始日 %s 晚于结束日 %s", start, end)
        return 2

    if end > yesterday:
        log.warning("结束日不能晚于昨天（今天是 %s），改成 %s", now, yesterday)
        end = yesterday
        if start > end:
            log.info("区间落在今天以内，没有完整的日期可汇总")
            return 0

    total = rebuild_range(start, end)
    log.info("完成：%s ~ %s，共 %d 行", start, end, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

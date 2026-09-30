"""用户看到的搜索记录：search_history。

一行 = 一次检索，不是一次请求。身份 = (user_id, kind, query, filters)，
由 schema/auth.sql 里的唯一索引强制 —— 所以翻页走 UPSERT 合并，不会堆行。

系统运行记录是另一张表（app/searchlog 的 search_log），它是"一次请求一行"。
两张表的区别就在这个问题上：翻页算不算新的一行。
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..db import get_pg

log = logging.getLogger(__name__)

KIND_OIRF = "oirf"
KIND_REPORT = "report"

_NOT_FILTERS = frozenset({"q", "page", "size", "highlight"})

_CONNECT_TIMEOUT = 2.0

UNAVAILABLE = (psycopg.OperationalError, RuntimeError)

_UPSERT = """
INSERT INTO search_history
       (user_id, kind, query, filters, last_page, size, result_total)
VALUES (%(user_id)s, %(kind)s, %(query)s, %(filters)s, %(last_page)s, %(size)s,
        %(result_total)s)
ON CONFLICT (user_id, kind, query, filters) DO UPDATE
   SET last_page    = GREATEST(search_history.last_page, EXCLUDED.last_page),
       size         = EXCLUDED.size,
       result_total = EXCLUDED.result_total,
       search_count = search_history.search_count + 1,
       last_seen_at = now()
"""

_SELECT = """
SELECT id, kind, query, filters, last_page, size, result_total, search_count,
       first_seen_at, last_seen_at
FROM search_history
WHERE user_id = %(user_id)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
ORDER BY last_seen_at DESC
LIMIT %(limit)s
"""


class Recordable(Protocol):

    page: int
    size: int

    def model_dump(self, *, mode: str = ..., exclude_none: bool = ...) -> dict[str, Any]: ...


def split_request(req: Recordable) -> tuple[str, dict[str, Any]]:
    """把请求拆成 (检索词, 筛选条件)"""
    dumped = req.model_dump(mode="json", exclude_none=True)
    query = dumped.pop("q", None) or ""
    return query, {k: v for k, v in dumped.items() if k not in _NOT_FILTERS}


def record_search(user_id: int, kind: str, req: Recordable,
                  result_total: int | None) -> None:
    try:
        query, filters = split_request(req)
        with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
            conn.execute(_UPSERT, {
                "user_id": user_id,
                "kind": kind,
                "query": query,
                "filters": Jsonb(filters),
                "last_page": req.page,
                "size": req.size,
                "result_total": result_total,
            })
    except Exception as exc:                          # noqa: BLE001
        log.warning("search_history not recorded: %s: %s",
                    type(exc).__name__, exc, exc_info=True)


def list_history(user_id: int, kind: Literal["oirf", "report"] | None = None,
                 limit: int = 20) -> list[dict[str, Any]]:
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT, {"user_id": user_id, "kind": kind, "limit": limit})
            rows = cur.fetchall()
    return rows

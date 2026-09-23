"""搜索历史的读写。"""
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

# 存储不可用：连不上 PG，或者 PG_DSN 没配（pg_dsn() 抛 RuntimeError）。
UNAVAILABLE = (psycopg.OperationalError, RuntimeError)

_INSERT = """
INSERT INTO search_history
       (user_id, kind, query, filters, page, size, result_total, latency_ms)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_SELECT = """
SELECT id, kind, query, filters, page, size, result_total, latency_ms, created_at
FROM search_history
WHERE user_id = %(user_id)s
  AND (%(kind)s::text IS NULL OR kind = %(kind)s)
ORDER BY created_at DESC
LIMIT %(limit)s
"""


class Recordable(Protocol):

    page: int
    size: int

    def model_dump(self, *, mode: str = ..., exclude_none: bool = ...) -> dict[str, Any]: ...


def _split(req: Recordable) -> tuple[str, dict[str, Any]]:
    dumped = req.model_dump(mode="json", exclude_none=True)
    query = dumped.pop("q", None) or ""
    return query, {k: v for k, v in dumped.items() if k not in _NOT_FILTERS}


def record_search(user_id: int, kind: str, req: Recordable, result_total: int | None,
                  latency_ms: int) -> None:
    try:
        query, filters = _split(req)
        with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
            conn.execute(_INSERT, (user_id, kind, query, Jsonb(filters),
                                   req.page, req.size, result_total, latency_ms))
    except UNAVAILABLE as exc:
        log.warning("search_history not recorded: %s: %s", type(exc).__name__, exc)


def list_history(user_id: int, kind: Literal["oirf", "report"] | None = None,
                 limit: int = 20) -> list[dict[str, Any]]:
    with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SELECT, {"user_id": user_id, "kind": kind, "limit": limit})
            rows = cur.fetchall()
    return rows


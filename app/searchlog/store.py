"""search_log: 一行 = 一次检索请求"""
from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from ..db import get_pg
from ..history.store import Recordable, split_request

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT = 2.0

_INSERT = """
INSERT INTO search_log
       (request_id, user_id, kind, query, filters, page, size,
        outcome, status_code, error_type, result_total, latency_ms)
VALUES (%(request_id)s, %(user_id)s, %(kind)s, %(query)s, %(filters)s, %(page)s,
        %(size)s, %(outcome)s, %(status_code)s, %(error_type)s, %(result_total)s,
        %(latency_ms)s)
"""


@dataclass
class Observation:
    request_id: str
    user_id: int
    kind: str
    query: str
    filters: dict[str, Any]
    page: int
    size: int
    status_code: int = 200
    error_type: str | None = None
    result_total: int | None = None
    latency_ms: int = field(default=0)

    def ok(self, result_total: int | None) -> None:
        self.result_total = result_total

    @property
    def outcome(self) -> str:
        return "ok" if self.error_type is None else "error"


def _status_of(exc: BaseException) -> int:
    if isinstance(exc, HTTPException):
        return exc.status_code
    if isinstance(exc, ValueError):
        return 400
    return 500


def _write(obs: Observation) -> None:
    try:
        with get_pg().connection(timeout=_CONNECT_TIMEOUT) as conn:
            conn.execute(_INSERT, {
                "request_id": obs.request_id,
                "user_id": obs.user_id,
                "kind": obs.kind,
                "query": obs.query,
                "filters": Jsonb(obs.filters),
                "page": obs.page,
                "size": obs.size,
                "outcome": obs.outcome,
                "status_code": obs.status_code,
                "error_type": obs.error_type,
                "result_total": obs.result_total,
                "latency_ms": obs.latency_ms,
            })
    except Exception as exc:                          # noqa: BLE001
        log.warning("search_log not recorded: %s: %s",
                    type(exc).__name__, exc, exc_info=True)


@contextmanager
def observe(kind: str, user_id: int, req: Recordable) -> Generator[Observation, None, None]:
    """记下一次请求：正常退出记 ok/200，抛异常记 error/状态码，然后原样抛出。"""
    query, filters = split_request(req)
    obs = Observation(
        request_id=secrets.token_hex(6),
        user_id=user_id,
        kind=kind,
        query=query,
        filters=filters,
        page=req.page,
        size=req.size,
    )
    started = time.perf_counter()

    try:
        yield obs
    except Exception as exc:
        obs.status_code = _status_of(exc)
        obs.error_type = type(exc).__name__
        obs.latency_ms = int((time.perf_counter() - started) * 1000)
        _write(obs)
        raise
    else:
        obs.latency_ms = int((time.perf_counter() - started) * 1000)
        _write(obs)
    finally:
        log.info(
            "search request_id=%s kind=%s user_id=%s page=%s size=%s"
            " outcome=%s status=%s total=%s latency_ms=%s",
            obs.request_id, obs.kind, obs.user_id, obs.page, obs.size,
            obs.outcome, obs.status_code, obs.result_total, obs.latency_ms,
        )

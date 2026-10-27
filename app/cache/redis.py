"""
检索结果缓存。

"""
from __future__ import annotations

import json
import logging
import re
import socket
import threading
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import redis

from ..config import ENABLE_REPORT_CACHE, REDIS_URL

logger = logging.getLogger(__name__)

_TIMEOUT = 0.1
_ERR_MAX = 200
_ERR_CREDS = re.compile(r"://[^@/\s]*@")

_lock = threading.Lock()
_client: redis.Redis | None = None
_errors = 0


def _ip_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.hostname:
        return url
    port = parts.port or 6379
    try:
        ip = socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)[0][4][0]
    except OSError:
        return url

    user = parts.username or ""
    if parts.password:
        user += f":{parts.password}"
    netloc = f"{user}@{ip}:{port}" if user else f"{ip}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def enabled() -> bool:
    return bool(redis is not None and ENABLE_REPORT_CACHE and REDIS_URL)


def get_redis() -> redis.Redis | None:
    global _client
    if not enabled():
        return None
    with _lock:
        if _client is None:
            _client = redis.Redis.from_url(
                _ip_url(REDIS_URL),
                socket_timeout=_TIMEOUT,
                socket_connect_timeout=_TIMEOUT,
            )
        return _client


def errors() -> int:
    with _lock:
        return _errors


def _note(action: str, key: str, exc: BaseException) -> None:
    global _errors
    with _lock:
        _errors += 1
    msg = _ERR_CREDS.sub("://***@", f"{type(exc).__name__}: {exc}")
    logger.warning("cache %s %s failed: %s", action, key, msg[:_ERR_MAX])


def _seconds_to_midnight(now: datetime) -> int:
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((nxt - now).total_seconds()))


def load(key: str) -> dict[str, Any] | None:
    client = get_redis()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:                      # noqa: BLE001
        _note("get", key, exc)
        return None
    if raw is None:
        return None

    try:
        value = json.loads(raw)
    except ValueError as exc:
        logger.warning("cache value %s is not json: %s", key, exc)
        drop(key)
        return None

    if not isinstance(value, dict) or "hits" not in value or "total" not in value:
        logger.warning("cache value %s has the wrong shape, dropping", key)
        drop(key)
        return None

    return value


def store(key: str, value: Any, *, now: datetime | None = None) -> None:
    client = get_redis()
    if client is None:
        return

    ttl = _seconds_to_midnight(now or datetime.now())
    try:
        client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
    except Exception as exc:                      # noqa: BLE001
        _note("set", key, exc)


def load_json(key: str) -> dict[str, Any] | None:
    """通用读取：只要求是 JSON 对象，不校验业务形状。"""
    client = get_redis()
    if client is None:
        return None

    try:
        raw = client.get(key)
    except Exception as exc:                      # noqa: BLE001
        _note("get", key, exc)
        return None
    if raw is None:
        return None

    try:
        value = json.loads(raw)
    except ValueError as exc:
        logger.warning("cache value %s is not json: %s", key, exc)
        drop(key)
        return None

    if not isinstance(value, dict):
        logger.warning("cache value %s is not an object, dropping", key)
        drop(key)
        return None

    return value


def store_json(key: str, value: Any, ttl: int) -> None:
    """通用写入，ttl 由调用方决定（秒）。"""
    client = get_redis()
    if client is None:
        return

    try:
        client.set(key, json.dumps(value, ensure_ascii=False), ex=max(1, int(ttl)))
    except Exception as exc:                      # noqa: BLE001
        _note("set", key, exc)


def drop(key: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:                      # noqa: BLE001
        logger.debug("cache delete %s failed: %s", key, exc)


def status() -> dict[str, Any]:
    if not enabled():
        return {"enabled": False}

    body: dict[str, Any] = {"enabled": True, "errors": errors()}
    try:
        client = get_redis()
        client.ping()
        body["keys"] = int(client.dbsize())
        body["ok"] = body["reachable"] = True
    except Exception as exc:                      # noqa: BLE001
        safe = _ERR_CREDS.sub("://***@", f"{type(exc).__name__}: {exc}")[:_ERR_MAX]
        body["ok"] = body["reachable"] = False
        body["error"] = safe
        logger.warning("readiness: redis unreachable: %s", safe)
    return body


__all__ = ["enabled", "get_redis", "load", "load_json", "store", "store_json",
           "drop", "errors", "status"]

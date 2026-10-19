"""query 向量缓存"""

from __future__ import annotations

import hashlib
import logging
import struct
import threading
from contextlib import contextmanager
from typing import Callable, Iterator

from embedding.spec import MODEL

from ..config import QUERY_VEC_ENABLED, QUERY_VEC_TIMEOUT_MS
from ..db import get_pg

_logger = logging.getLogger(__name__)

_MODEL = str(MODEL["name"])
_DIM = int(MODEL["dims"])
_INSTRUCTION_HASH = hashlib.sha256(
    str(MODEL.get("query_instruction") or "").encode("utf-8")).digest()[:16]

# '<Ne' is IEEE 754 binary16; the api image has no numpy (it is encoder-only).
_HALF = struct.Struct(f"<{_DIM}e")

# 拿不到连接就不再等：缓存是可选路径，宁可当未命中，也不占住请求线程。
_POOL_TIMEOUT_S = 0.2

_SELECT = ("select vec from query_vec"
           " where model = %s and dim = %s"
           "   and instruction_hash = %s and text_hash = %s")
_INSERT = ("insert into query_vec (model, dim, instruction_hash, text_hash, vec)"
           " values (%s, %s, %s, %s, %s)"
           " on conflict (model, dim, instruction_hash, text_hash) do nothing")

_inflight: dict[bytes, list] = {}
_inflight_lock = threading.Lock()

_last_error: str | None = None
_error_lock = threading.Lock()


def enabled() -> bool:
    return QUERY_VEC_ENABLED


def text_hash(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def identity() -> tuple[str, int, bytes]:
    """(model, dim, instruction_hash)——灌库脚本与线上读写共用同一份键材料。"""
    return _MODEL, _DIM, _INSTRUCTION_HASH


def pack(vector: list[float]) -> bytes | None:
    """把向量打成 fp16；长度或数值不合法时返回 None。"""
    if len(vector) != _DIM:
        _logger.warning("encoder returned %d dims, spec says %d: not stored", len(vector), _DIM)
        return None
    try:
        return _HALF.pack(*vector)
    except (struct.error, OverflowError, TypeError) as exc:
        _logger.warning("cannot pack vector as fp16 (%s): not stored", exc)
        return None


def _note_error(exc: BaseException) -> None:
    global _last_error
    message = f"{type(exc).__name__}: {exc}"
    with _error_lock:
        if message == _last_error:
            return
        _last_error = message
    _logger.warning("query_vec unavailable, falling back to encoder: %s", message)


def _clear_error() -> None:
    global _last_error
    with _error_lock:
        _last_error = None


def decode(raw: bytes) -> list[float] | None:
    if len(raw) != _DIM * 2:
        _logger.warning("query_vec length %d != %d, treating as a miss", len(raw), _DIM * 2)
        return None
    return list(_HALF.unpack(raw))


def resolve(text: str) -> list[float] | None:
    if not QUERY_VEC_ENABLED:
        return None
    try:
        with get_pg().connection(timeout=_POOL_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                cur.execute(f"set local statement_timeout = {int(QUERY_VEC_TIMEOUT_MS)}")
                cur.execute(_SELECT, (_MODEL, _DIM, _INSTRUCTION_HASH, text_hash(text)))
                row = cur.fetchone()
    except Exception as exc:                                    # noqa: BLE001
        _note_error(exc)
        return None
    if row is None:
        _clear_error()
        return None
    vector = decode(row[0])
    if vector is not None:
        _clear_error()
    return vector


def store(text: str, vector: list[float]) -> bool:
    if not QUERY_VEC_ENABLED:
        return False
    raw = pack(vector)
    if raw is None:
        return False
    try:
        with get_pg().connection(timeout=_POOL_TIMEOUT_S) as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT, (_MODEL, _DIM, _INSTRUCTION_HASH, text_hash(text), raw))
    except Exception as exc:                                    # noqa: BLE001
        _note_error(exc)
        return False
    _clear_error()
    return True


@contextmanager
def _singleflight(key: bytes) -> Iterator[None]:
    with _inflight_lock:
        slot = _inflight.get(key)
        if slot is None:
            slot = [threading.Lock(), 0]
            _inflight[key] = slot
        slot[1] += 1
    slot[0].acquire()
    try:
        yield
    finally:
        slot[0].release()
        with _inflight_lock:
            slot[1] -= 1
            if slot[1] == 0:
                _inflight.pop(key, None)


def get_or_encode(text: str,
                  encode: Callable[[str], list[float] | None]) -> list[float] | None:
    if not QUERY_VEC_ENABLED:
        return encode(text)

    hit = resolve(text)
    if hit is not None:
        return hit

    with _singleflight(text_hash(text)):
        hit = resolve(text)
        if hit is not None:
            return hit
        vector = encode(text)
        if vector is not None:
            store(text, vector)
        return vector


__all__ = ["enabled", "text_hash", "identity", "pack", "decode", "resolve", "store",
           "get_or_encode"]

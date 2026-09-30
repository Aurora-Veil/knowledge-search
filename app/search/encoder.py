"""
编码器入口：ENCODER_URL 有值走远端服务，否则用进程内 Encoder。
"""

import logging
import threading
import time
from typing import Any, Sequence

import httpx

from ..config import ENCODER_TIMEOUT_S, ENCODER_URL

# from embedding.encoder import Encoder

_logger = logging.getLogger(__name__)

_FAILS_TO_OPEN = 3
_COOLDOWN_S = 5.0
_PROBE_TIMEOUT_S = 1.0

_encoder = None
_lock = threading.Lock()
_last_fail: str | None = None


class _Breaker:

    def __init__(self, fails: int = _FAILS_TO_OPEN, cooldown: float = _COOLDOWN_S) -> None:
        self._fails = fails
        self._cooldown = cooldown
        self._count = 0
        self._until = 0.0
        self._probe = False
        self._probe_until = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if now < self._until:
                return False
            if self._count >= self._fails:
                if self._probe and now < self._probe_until:                # 冷却后只放行一个
                    return False
                self._probe = True
                self._probe_until = now + self._cooldown
                return True
            return True

    def ok(self) -> None:
        with self._lock:
            self._count = 0
            self._until = 0.0
            self._probe = False

    def fail(self) -> None:
        with self._lock:
            self._probe = False
            self._count += 1
            if self._count >= self._fails:
                self._until = time.monotonic() + self._cooldown

    def open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._until or (
                self._count >= self._fails and self._probe)


_breaker = _Breaker()


class RemoteEncoder:
    def __init__(self, url: str, timeout: float = ENCODER_TIMEOUT_S) -> None:
        self.url = url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=16),
        )
        self._dim: int | None = None

    def _encode(self, texts: Sequence[str], kind: str) -> list[list[float]]:
        res = self._client.post(f"{self.url}/encode",
                                json={"texts": list(texts), "kind": kind})
        res.raise_for_status()
        body = res.json()
        self._dim = int(body["dim"])
        return body["vectors"]

    def encode_query(self, query: str) -> list[float]:
        return self._encode([query], "query")[0]

    def encode_queries(self, queries: Sequence[str]) -> list[list[float]]:
        return self._encode(queries, "query")

    @property
    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": False, "error": None}
        try:
            res = self._client.get(f"{self.url}/health", timeout=_PROBE_TIMEOUT_S)
            res.raise_for_status()
            body = res.json()
            out["ok"] = bool(body.get("ok"))
            out["dim"] = self._dim = int(body.get("dim"))
            out["device"] = body.get("device")
        except Exception as exc:  # noqa: BLE001
            out["error"] = f"{type(exc).__name__}: {exc}"
        return out

def _make_encoder() -> Any:
    if ENCODER_URL:
        _logger.info("encoder: remote %s (timeout %ss)", ENCODER_URL, ENCODER_TIMEOUT_S)
        return RemoteEncoder(ENCODER_URL)
    _logger.info("encoder: in-process")
    from embedding.encoder import Encoder

    return Encoder()


def get_encoder() -> Any:
    global _encoder
    with _lock:
        if _encoder is None:
            _encoder = _make_encoder()
        return _encoder


def _note_failure(exc: BaseException) -> None:
    global _last_fail
    signature = f"{type(exc).__name__}: {exc}"
    with _lock:
        if signature == _last_fail:                   # 同一次失败只记一条
            return
        _last_fail = signature
    _logger.warning("encode failed, lexical only: %s", signature)


def _note_success() -> None:
    global _last_fail
    with _lock:
        _last_fail = None


def encode_query_optional(query: str) -> list[float] | None:
    if not _breaker.allow():
        return None
    try:
        vector = get_encoder().encode_query(query)
    except Exception as exc:                          # noqa: BLE001
        _breaker.fail()
        _note_failure(exc)
        return None
    _breaker.ok()
    _note_success()
    return vector


def encode_queries_optional(queries: Sequence[str]) -> list[list[float]] | None:
    if not queries:
        return []
    if not _breaker.allow():
        return None
    try:
        vectors = get_encoder().encode_queries(queries)
    except Exception as exc:                          # noqa: BLE001
        _breaker.fail()
        _note_failure(exc)
        return None
    _breaker.ok()
    _note_success()
    return vectors


def status() -> dict[str, Any]:
    out: dict[str, Any] = {
        "mode": "remote" if ENCODER_URL else "in-process",
        "ok": True,
        "url": ENCODER_URL or None,
        "circuit_open": _breaker.open(),
        "error": None,
    }
    if ENCODER_URL:
        out.update(get_encoder().status)
    return out


def warmup() -> None:
    get_encoder().encode_query("warmup")


def _start_warmup() -> None:
    threading.Thread(target=_warmup, name="encoder-warmup", daemon=True).start()


def _warmup() -> None:
    _logger.info("encoder warmup started")
    try:
        warmup()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("encoder warmup failed: %s: %s", type(exc).__name__, exc)
    else:
        _logger.info("encoder warmup done")
"""
独立编码服务：单进程、单份模型、query 合批。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import Any, Literal

import anyio
import anyio.to_thread
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import (
    ENCODER_BATCH_WAIT_MS,
    ENCODER_MAX_BATCH,
    ENCODER_PORT,
    ENCODER_SERVER_TIMEOUT_S,
)

log = logging.getLogger(__name__)

TEXTS_MAX = 256

SERVER_TIMEOUT_S = ENCODER_SERVER_TIMEOUT_S


class EncodeRequest(BaseModel):
    texts: list[str] = Field(..., max_length=TEXTS_MAX)
    kind: Literal["query", "passage"]


_forward_lock = threading.Lock()


def _load_encoder() -> Any:
    from .encoder import Encoder, resolve_snapshot

    encoder = Encoder()
    encoder.encode_query("warmup")
    log.info("encoder ready: %s on %s, dim=%s",
             resolve_snapshot().name, encoder.device, encoder.dim)
    return encoder


def _encode_sync(texts: list[str], kind: str) -> list[list[float]]:
    with _forward_lock:
        if kind == "query":
            return _encoder.encode_queries(texts)
        return _encoder.encode_passages(texts)


class Batcher:

    def __init__(self, max_batch: int = ENCODER_MAX_BATCH,
                 wait_ms: float = ENCODER_BATCH_WAIT_MS) -> None:
        self.max_batch = max(int(max_batch), 1)
        self.wait = max(float(wait_ms), 0.0) / 1000.0
        self.inbox: asyncio.Queue[list[tuple[list[str], asyncio.Future]]] = asyncio.Queue()
        self.last_fail: str | None = None
        self.last_batch = 0
        self.last_batch_ms = 0.0
        self.batches = 0
        self.texts = 0

    def submit(self, texts: list[str]) -> asyncio.Future:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.inbox.put_nowait((texts, fut))
        return fut

    async def run(self) -> None:
        while True:
            first = await self.inbox.get()
            batch = [first]
            total = len(first[0])
            await asyncio.sleep(self.wait)             # 合批窗口
            while total < self.max_batch:
                try:
                    item = self.inbox.get_nowait()
                except asyncio.QueueEmpty:
                    break
                batch.append(item)
                total += len(item[0])
            await self._encode(batch, total)

    async def _encode(self, batch: list, total: int) -> None:
        started = asyncio.get_running_loop().time()
        try:
            vectors = await anyio.to_thread.run_sync(
                _encode_sync, [t for texts, _ in batch for t in texts], "query")
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # noqa: BLE001
            self._failed(exc, batch)
            return

        self._recovered()
        self.last_batch = total
        self.last_batch_ms = (asyncio.get_running_loop().time() - started) * 1000
        self.batches += 1
        self.texts += total
        offset = 0
        for texts, fut in batch:
            chunk = vectors[offset:offset + len(texts)]
            offset += len(texts)
            if not fut.cancelled():
                fut.set_result(chunk)
        log.debug("encoded %s texts (batch of %s) in %.1f ms",
                  total, len(batch), (asyncio.get_running_loop().time() - started) * 1000)

    def _failed(self, exc: BaseException, batch: list) -> None:
        signature = f"{type(exc).__name__}: {exc}"
        if signature != self.last_fail:                # 同一次失败只记一条
            log.error("encode batch failed (lexical-only for callers): %s", signature)
            self.last_fail = signature
        for _, fut in batch:
            if not fut.done():
                fut.set_exception(exc)

    def _recovered(self) -> None:
        if self.last_fail is not None:
            log.info("encode batch recovered")
            self.last_fail = None


_batcher: Batcher | None = None
_worker: asyncio.Task | None = None
_encoder: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _batcher, _worker, _encoder
    _encoder = await anyio.to_thread.run_sync(_load_encoder)
    _batcher = Batcher()
    _worker = asyncio.create_task(_batcher.run())
    try:
        yield
    finally:
        _worker.cancel()


app = FastAPI(title="OIRF encoder service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"ok": _encoder is not None, "dim": _encoder.dim, "device": _encoder.device}


@app.get("/metrics")
async def metrics() -> dict:
    """合批队列深度与最近一批大小，压测采样用。"""
    if _batcher is None:
        return {"queue": 0, "last_batch": 0, "batches": 0, "texts": 0}
    return {"queue": _batcher.inbox.qsize(), "last_batch": _batcher.last_batch,
            "last_batch_ms": round(_batcher.last_batch_ms, 1),
            "batches": _batcher.batches, "texts": _batcher.texts}


@app.post("/encode")
async def encode(req: EncodeRequest) -> dict:
    if _encoder is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")

    texts = req.texts
    if not texts:
        return {"vectors": [], "dim": _encoder.dim}

    if req.kind == "passage":                          # 直通，不进合批
        vectors = await _wait(anyio.to_thread.run_sync(_encode_sync, texts, "passage"))
        return {"vectors": vectors, "dim": _encoder.dim}

    futures = [_batcher.submit(texts[i:i + ENCODER_MAX_BATCH])
               for i in range(0, len(texts), ENCODER_MAX_BATCH)]
    chunks = await _wait(_gather(futures))
    return {"vectors": [v for chunk in chunks for v in chunk], "dim": _encoder.dim}


async def _gather(futures: list[asyncio.Future]) -> list:
    done, pending = await asyncio.wait(futures)
    failure = next((f.exception() for f in done
                    if not f.cancelled() and f.exception() is not None), None)
    if failure is None:
        return [f.result() for f in futures]
    for fut in pending:
        fut.cancel()
    raise failure


async def _wait(awaitable: Any) -> Any:
    try:
        with anyio.fail_after(SERVER_TIMEOUT_S):
            return await awaitable
    except TimeoutError:
        raise HTTPException(status_code=504, detail="encode timeout") from None


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(app, host="127.0.0.1", port=ENCODER_PORT, log_level="info")


if __name__ == "__main__":
    main()

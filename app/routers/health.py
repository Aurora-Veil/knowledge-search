"""GET /api/v1/health, GET /api/v1/health/ready"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException

from .. import db
from ..config import ES_HEALTH_TIMEOUT, PG_HEALTH_TIMEOUT
from ..search.encoder import status as encoder_status

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])

_ERR_MAX = 200
_ERR_CREDS = re.compile(r"://[^@/\s]*@")


def _safe_err(exc: BaseException) -> str:
    """Error text, with any user:password@ inside a URL masked out."""
    msg = _ERR_CREDS.sub("://***@", f"{type(exc).__name__}: {exc}")
    return msg[:_ERR_MAX]


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "oirf-search"}


def _check_es() -> dict:
    # 不用 _cluster/health：那要集群级 monitor 权限，应用用户只有索引级的。
    # 改走真实检索这条路，有主分片未分配时 _shards.failed 会大于 0。
    try:
        es = db.get_es().options(max_retries=0, request_timeout=ES_HEALTH_TIMEOUT)
        res = es.search(index="knowledge_*", size=0,
                        ignore_unavailable=True, allow_no_indices=True)
        shards = res.get("_shards", {})
        total = int(shards.get("total", 0))
        failed = int(shards.get("failed", 0))

        if total == 0:
            status = "unavailable"
        elif failed:
            status = "degraded"
        else:
            status = "available"

        return {
            "ok": status == "available",
            "status": status,
            "shards": f"{int(shards.get('successful', 0))}/{total}",
        }
    except Exception as exc:                      # noqa: BLE001
        log.warning("readiness: elasticsearch unreachable: %s", exc)
        return {"status": "unreachable", "ok": False, "error": _safe_err(exc)}


def _check_mongo() -> dict:
    try:
        db.get_mongo().admin.command("ping")
        return {"ok": True}
    except Exception as exc:                      # noqa: BLE001
        log.warning("readiness: mongodb unreachable: %s", exc)
        return {"ok": False, "error": _safe_err(exc)}


def _check_pg() -> dict:
    try:
        with db.get_pg().connection(timeout=PG_HEALTH_TIMEOUT) as conn:
            conn.execute("SELECT 1")
        return {"ok": True}
    except Exception as exc:                      # noqa: BLE001
        log.warning("readiness: postgresql unreachable: %s", exc)
        return {"ok": False, "error": _safe_err(exc)}


@router.get("/health/ready")
def health_ready() -> dict:
    es = _check_es()
    mongo = _check_mongo()
    postgres = _check_pg()
    encoder = encoder_status()

    body = {
        "ready": bool(es["ok"] and mongo["ok"] and postgres["ok"]),
        "elasticsearch": es,
        "mongodb": mongo,
        "postgresql": postgres,
        "encoder": encoder,
    }
    if not body["ready"]:
        raise HTTPException(status_code=503, detail=body)
    return body

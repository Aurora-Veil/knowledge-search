"""FastAPI app entrypoint"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .config import ES_HEALTH_TIMEOUT
from .mcp import mcp
from .routers import associations, objects, projects, reports, search
from .search.encoder import _start_warmup

log = logging.getLogger(__name__)

mcp_app = mcp.streamable_http_app(streamable_http_path="/")

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        _start_warmup() 
        yield
    db.close()


app = FastAPI(
    title="OIRF Knowledge-Graph Search API",
    version="0.1.0",
    description="MongoDB + Elasticsearch search api, also served over MCP at /mcp",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# @app.middleware("http")
# async def ui_no_cache(request: Request, call_next):
#     """静态页面每次都回源校验。"""
#     response = await call_next(request)
#     if request.url.path.startswith(("/ui", "/ui/")):
#         response.headers["Cache-Control"] = "no-cache"
#     return response

app.include_router(search.router)
app.include_router(reports.router)
app.include_router(objects.router)
app.include_router(associations.router)
app.include_router(projects.router)


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "service": "oirf-search"}


_ERR_MAX = 200
_ERR_CREDS = re.compile(r"://[^@/\s]*@")


def _safe_err(exc: BaseException) -> str:
    msg = _ERR_CREDS.sub("://***@", f"{type(exc).__name__}: {exc}")
    return msg[:_ERR_MAX]


@app.get("/api/v1/health/ready")
def health_ready() -> dict:
    try:
        es_health = db.get_es().cluster.health(index="knowledge_*", timeout=f"{ES_HEALTH_TIMEOUT}s")
        es_status = es_health["status"]
        es = {"status": es_status, "ok": es_status != "red"}
    except Exception as exc:                      # noqa: BLE001
        log.warning("readiness: elasticsearch unreachable: %s", exc)
        es = {"status": "unreachable", "ok": False, "error": _safe_err(exc)}

    try:
        db.get_mongo().admin.command("ping")
        mongo = {"ok": True}
    except Exception as exc:                      # noqa: BLE001
        log.warning("readiness: mongodb unreachable: %s", exc)
        mongo = {"ok": False, "error": _safe_err(exc)}

    ready = bool(es["ok"] and mongo["ok"])
    body = {"ready": ready, "elasticsearch": es, "mongodb": mongo}
    if not ready:
        raise HTTPException(status_code=503, detail=body)
    return body

app.mount("/ui", StaticFiles(directory="static", html=True))
app.mount("/mcp", mcp_app)

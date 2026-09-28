"""FastAPI app entrypoint -- assembly only.

Route behaviour lives in app/routers/*.py; this file only wires things together.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .mcp import mcp
from .routers import associations, auth, health, objects, projects, reports, search, history
from .search.encoder import _start_warmup

# 模块级：多进程 spawn 出的子进程也会 import 这里，run.py 的 __main__ 不会执行
# root 日志由 mcp SDK 在 import 时配好（INFO + rich），这里只压掉 httpx 的 INFO：
# 它会把完整 URL 打出来，查询词会进日志
logging.getLogger("httpx").setLevel(logging.WARNING)

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

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(search.router)
app.include_router(reports.router)
app.include_router(objects.router)
app.include_router(associations.router)
app.include_router(projects.router)
app.include_router(history.router)

app.mount("/ui", StaticFiles(directory="static", html=True))
app.mount("/mcp", mcp_app)

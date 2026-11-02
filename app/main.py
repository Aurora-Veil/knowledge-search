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
from .routers import admin, associations, auth, health, objects, projects, reports, search, history, stats
from .search.encoder import _start_warmup

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

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(search.router)
app.include_router(reports.router)
app.include_router(objects.router)
app.include_router(associations.router)
app.include_router(projects.router)
app.include_router(history.router)
app.include_router(admin.router)
app.include_router(stats.router)

app.mount("/ui", StaticFiles(directory="static", html=True))
app.mount("/mcp", mcp_app)

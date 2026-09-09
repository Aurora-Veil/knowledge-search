"""FastAPI 入口。

运行：`uvicorn app.main:app --reload`（或 `python run.py`）。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .routers import search

app = FastAPI(
    title="OIRF Knowledge-Graph Search API",
    version="0.1.0",
    description="MongoDB (authority) + Elasticsearch 知识图谱搜索接口。搜索走 ES，完整对象回 Mongo 补权威字段。",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "service": "oirf-search"}


@app.on_event("shutdown")
def _shutdown() -> None:
    db.close()

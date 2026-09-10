"""FastAPI app entrypoint"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .routers import objects, search

app = FastAPI(
    title="OIRF Knowledge-Graph Search API",
    version="0.1.0",
    description="MongoDB + Elasticsearch search api",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(objects.router)


@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "service": "oirf-search"}


@app.on_event("shutdown")
def _shutdown() -> None:
    db.close()

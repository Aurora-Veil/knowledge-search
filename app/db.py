from __future__ import annotations

from typing import Any

from elasticsearch import Elasticsearch
from psycopg_pool import ConnectionPool
from pymongo import MongoClient

from .config import (
    DB_NAME,
    ES_HEALTH_TIMEOUT,
    MONGO_TIMEOUT_MS,
    MONGO_URI,
    es_auth,
    es_hosts,
    pg_dsn,
)

_es: Elasticsearch | None = None
_mongo: MongoClient | None = None
_pg: ConnectionPool | None = None


def get_es() -> Elasticsearch:
    global _es
    if _es is None:
        _es = Elasticsearch(
            es_hosts(),
            basic_auth=es_auth(),
            request_timeout=ES_HEALTH_TIMEOUT,
        )
    return _es


def get_mongo() -> MongoClient:
    global _mongo
    if _mongo is None:
        # serverSelectionTimeoutMS defaults to 30s -- far too long for a web
        # request, and it made /health/ready hang for half a minute.
        _mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=MONGO_TIMEOUT_MS)
    return _mongo


def get_db():
    return get_mongo()[DB_NAME]


def get_pg() -> ConnectionPool:
    global _pg
    if _pg is None:
        _pg = ConnectionPool(pg_dsn(), min_size=1, max_size=10, open=True)
    return _pg


def close() -> None:
    global _es, _mongo, _pg
    if _es is not None:
        _es.close()
        _es = None
    if _mongo is not None:
        _mongo.close()
        _mongo = None
    if _pg is not None:
        _pg.close()
        _pg = None


from __future__ import annotations

from elasticsearch import Elasticsearch
from pymongo import MongoClient

from .config import DB_NAME, ES_URL, MONGO_URI

_es: Elasticsearch | None = None
_mongo: MongoClient | None = None


def get_es() -> Elasticsearch:
    global _es
    if _es is None:
        _es = Elasticsearch(ES_URL)
    return _es


def get_mongo() -> MongoClient:
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(MONGO_URI)
    return _mongo


def get_db():
    return get_mongo()[DB_NAME]


def close() -> None:
    global _es, _mongo
    if _es is not None:
        _es.close()
        _es = None
    if _mongo is not None:
        _mongo.close()
        _mongo = None

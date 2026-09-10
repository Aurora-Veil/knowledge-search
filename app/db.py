from __future__ import annotations

from typing import Any

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


# 「调用方传了就用它（测试可注入），否则用进程内单例」的判定只此一处。
# 关键：不能用 `es or get_es()` / `db or get_db()` —— pymongo 的 Database/Collection
# 显式禁用了真值测试（`Database.__bool__` 会抛 NotImplementedError），
# 一旦调用方把数据库对象传进来，`or` 就会把整条路径炸掉。
def resolve_es(es: Elasticsearch | None = None) -> Elasticsearch:
    return get_es() if es is None else es


def resolve_db(db: Any = None) -> Any:
    return get_db() if db is None else db

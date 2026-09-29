from __future__ import annotations

import os
import warnings
from pathlib import Path

from dotenv import load_dotenv

from embedding.config import (
    ENCODER_BATCH_WAIT_MS,
    ENCODER_MAX_BATCH,
    ENCODER_PORT,
    ENCODER_SERVER_TIMEOUT_S,
    ENCODER_TIMEOUT_S,
    ENCODER_URL,
)

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "knowledge_db")
MONGO_TIMEOUT_MS = int(os.getenv("MONGO_TIMEOUT_MS", "3000"))

# Elasticsearch
_ES_URL_DEFAULT = "http://localhost:9200"
ES_URL = os.getenv("ES_URL", _ES_URL_DEFAULT)
ES_USER = os.getenv("ES_USER", "")
ES_PASSWORD = os.getenv("ES_PASSWORD", "")

#   ES_URL=http://localhost:9200
#   ES_URL=http://localhost:9200,http://localhost:9201,http://localhost:9202

ES_HOSTS: list[str] = [u.strip() for u in ES_URL.replace(";", ",").split(",") if u.strip()]

ES_HOSTS = ES_HOSTS or [_ES_URL_DEFAULT]

ES_HEALTH_TIMEOUT = float(os.getenv("ES_HEALTH_TIMEOUT", "2"))
PG_HEALTH_TIMEOUT = float(os.getenv("PG_HEALTH_TIMEOUT", "2"))

# 单次检索给 ES 的时间。早先这里复用健康检查的 2 秒，上万篇的索引下会误杀检索。
ES_REQUEST_TIMEOUT = float(os.getenv("ES_REQUEST_TIMEOUT", "10"))


def es_hosts() -> list[str]:
    return list(ES_HOSTS)

# Vector search. 
ENABLE_VECTOR_SEARCH = True

# API processes. One pool per process, connections = WEB_WORKERS * PG_POOL_MAX,
# against PG max_connections = 100.
WEB_WORKERS = int(os.getenv("WEB_WORKERS", "4"))
PG_POOL_MAX = int(os.getenv("PG_POOL_MAX", "10"))

# This box's ES search thread pool, int((16 * 3) / 2) + 1. Only the ES side
# changes it, so it lives here rather than in the env.
_ES_POOL_SIZE = 25

# Per process. Fusing BM25 and kNN means two ES requests per index
# (the Retriever API RRF is disabled on Basic), so in flight is
# WEB_WORKERS * this. Unset spreads the pool across workers: 4 -> 6, 8 -> 3.
_ES_SEARCH_WORKERS_ENV = os.getenv("ES_SEARCH_WORKERS")
ES_SEARCH_WORKERS = (int(_ES_SEARCH_WORKERS_ENV) if _ES_SEARCH_WORKERS_ENV
                     else max(1, _ES_POOL_SIZE // WEB_WORKERS))


def _check_concurrency() -> None:
    if ENCODER_TIMEOUT_S >= ENCODER_SERVER_TIMEOUT_S:
        raise RuntimeError(
            f"ENCODER_TIMEOUT_S({ENCODER_TIMEOUT_S}) >= 编码服务兜底超时"
            f"({ENCODER_SERVER_TIMEOUT_S})：客户端会先放弃，调小 ENCODER_TIMEOUT_S。"
        )
    pg = WEB_WORKERS * PG_POOL_MAX
    if pg > 100:
        raise RuntimeError(
            f"WEB_WORKERS({WEB_WORKERS}) * PG_POOL_MAX({PG_POOL_MAX}) = {pg} > 100："
            "PG max_connections 会被打满，调小其中一个。"
        )
    es = WEB_WORKERS * ES_SEARCH_WORKERS
    if es > _ES_POOL_SIZE:
        warnings.warn(
            f"WEB_WORKERS({WEB_WORKERS}) * ES_SEARCH_WORKERS({ES_SEARCH_WORKERS}) = {es}"
            f" 超过 ES 搜索线程池({_ES_POOL_SIZE})：多出来的检索会在 ES 侧排队，"
            "只影响延迟，不影响正确性。",
            stacklevel=2,
        )


_check_concurrency()

OBJECT_TYPES: tuple[str, ...] = ("source", "evidence", "viewpoint")

INDEX_BY_TYPE: dict[str, str] = {
    "source": "knowledge_source",
    "evidence": "knowledge_evidence",
    "viewpoint": "knowledge_viewpoint",
}

# object_type → Mongo collection
COLLECTION_BY_TYPE: dict[str, str] = {
    "source": "sources",
    "evidence": "evidence",
    "viewpoint": "viewpoints",
}


def es_auth() -> tuple[str, str]:
    if not ES_USER or not ES_PASSWORD:
        raise RuntimeError(
            "ES_USER / ES_PASSWORD 未设置：ES 已开启 security，连接需要凭据。"
            "请先 `cp .env.example .env` 并填入用户名与密码。"
        )
    return ES_USER, ES_PASSWORD


PG_DSN = os.getenv("PG_DSN", "")


SECRET_KEY = os.getenv("SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))


def pg_dsn() -> str:
    if not PG_DSN:
        raise RuntimeError(
            "PG_DSN 未设置：用户数据需要 PostgreSQL。"
            "请先 `cp .env.example .env` 并填入连接串。"
        )
    return PG_DSN


def jwt_secret() -> str:
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY 未设置：签发登录令牌需要签名密钥。"
            "生成一个：python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )
    return SECRET_KEY
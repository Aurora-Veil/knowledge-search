from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

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


def es_hosts() -> list[str]:
    return list(ES_HOSTS)

# Vector search. 
ENABLE_VECTOR_SEARCH = True

# Fusing BM25 and kNN means two ES requests per index
# ES Retriever API RRF disable for Basic :(
ES_SEARCH_WORKERS = 12

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
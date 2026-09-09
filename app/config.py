"""全局配置：连接、库、索引名、缺省项目。

与 docs/search-api-design.md §5 对齐。索引名与 full_sync.py 的 INDICES 一致。
"""
from __future__ import annotations

MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "knowledge_db"

ES_URL = "http://localhost:9200"

# 三种对象类型，顺序即 type=all 时的合并顺序
OBJECT_TYPES: tuple[str, ...] = ("source", "evidence", "viewpoint")

INDEX_BY_TYPE: dict[str, str] = {
    "source": "knowledge_source",
    "evidence": "knowledge_evidence",
    "viewpoint": "knowledge_viewpoint",
}

# object_type → Mongo 集合名（注意 evidence 是单数、source/viewpoint 是复数，勿写错）
COLLECTION_BY_TYPE: dict[str, str] = {
    "source": "sources",
    "evidence": "evidence",
    "viewpoint": "viewpoints",
}

# §5.0 定稿：project_id 缺省 = 当前项目；显式传跨项目
DEFAULT_PROJECT_ID = 1

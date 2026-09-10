# ingest.py —— 把 reasoning/ 下三个实体 JSON 入库到 Mongo（权威库 knowledge_db）
#
# id 模型（已确认）：
#   入库时丢弃原始 JSON 的生成期 int id，让 Mongo 自产 _id；
#   插入后再把 id 回写为本次插入得到的 _id。
#   结果：id == _id == ObjectId == ES _id（全局唯一），无需复合键。
import os
import json

from pymongo import ASCENDING

from app.config import COLLECTION_BY_TYPE                     # 集合名唯一来源
from app.db import close, get_db                              # 连接唯一来源

BASE      = os.path.dirname(os.path.abspath(__file__))        # 本脚本所在目录（项目根）

ENTITIES = {
    "source":    {"file": "source.json",    "collection": COLLECTION_BY_TYPE["source"],    "key": "sources"},
    "evidence":  {"file": "evidence.json",  "collection": COLLECTION_BY_TYPE["evidence"],  "key": "evidence"},
    "viewpoint": {"file": "viewpoint.json", "collection": COLLECTION_BY_TYPE["viewpoint"], "key": "viewpoints"},
}

# 旧的复合主键迁移备份，id 模型已变更，已失效，清库时一并删除
STALE_BACKUPS = ("_bk_sources", "_bk_evidence", "_bk_viewpoints")


def build_path(cfg: dict) -> str:
    return os.path.join(BASE, "reasoning", cfg["file"])


def load_docs(cfg: dict) -> list:
    with open(build_path(cfg), encoding="utf-8") as f:
        return json.load(f)[cfg["key"]]


def create_indexes(coll) -> None:
    """查询支持索引（唯一性已交给 _id，无需 unique）。"""
    coll.create_index([("project_id", ASCENDING)])
    coll.create_index([("oirf_id", ASCENDING)])
    coll.create_index([("project_id", ASCENDING), ("oirf_id", ASCENDING)])


def clear_all(db) -> None:
    """清空目标 collection 并删除失效备份。"""
    for cfg in ENTITIES.values():
        db.drop_collection(cfg["collection"])
    for bk in STALE_BACKUPS:
        if bk in db.list_collection_names():
            db.drop_collection(bk)


def ingest_entity(db, name: str) -> int:
    cfg = ENTITIES[name]
    coll = db[cfg["collection"]]
    create_indexes(coll)

    docs = load_docs(cfg)
    for d in docs:
        d.pop("id", None)                      # 丢弃生成期 int id，让 Mongo 自产 _id
        inserted = coll.insert_one(d)          # _id = 本次插入的 ObjectId
        coll.update_one({"_id": inserted.inserted_id},
                        {"$set": {"id": inserted.inserted_id}})   # id = _id
    return coll.count_documents({})


def main() -> None:
    try:
        db = get_db()
        clear_all(db)
        for name in ENTITIES:
            print(f"{ENTITIES[name]['collection']}: count = {ingest_entity(db, name)}")
    finally:
        close()


if __name__ == "__main__":
    main()

"""ingest.py —— 把 reasoning/ 下三个实体 JSON 重灌进 Mongo（权威库 knowledge_db）。

id 模型（已确认）：丢弃原始 JSON 的生成期 int id，让 Mongo 自产 _id，再回写 id = _id；
结果 id == _id == ObjectId == ES _id（全局唯一），无需复合键。

清库是破坏性动作，必须显式确认：
    python ingest.py --dry-run   只看将清空什么、将写入多少条
    python ingest.py --yes       真正执行（drop 三集合 + 删 _bk_* + 重灌）
    python ingest.py             不带确认 → 拒绝执行并说明会 drop 哪些集合、怎么确认

注意：重灌会生成**新的 ObjectId**（id = _id 随之变新），ES 里按旧 _id 存的文档会全部失配，
所以重灌后要接着跑 `python -m app.sync recreate`（删索引重建 + 全量重灌）。
"""
import argparse
import json
import os
import sys

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


def plan(db) -> dict:
    """将清空的集合（含现有条数）/ 现存失效备份 / 将写入的 JSON（含条数）。"""
    return {
        "drop": {cfg["collection"]: db[cfg["collection"]].count_documents({})
                 for cfg in ENTITIES.values()},
        "backups": [bk for bk in STALE_BACKUPS if bk in db.list_collection_names()],
        "write": {cfg["collection"]: len(load_docs(cfg)) for cfg in ENTITIES.values()},
    }


def print_plan(p: dict) -> None:
    print("== 将清空（drop 后重灌）==")
    for coll, n in p["drop"].items():
        print(f"  {coll}: 现有 {n} 条 → 将被删除")
    print("== 将删除的失效备份 ==")
    print("  " + ("、".join(p["backups"]) if p["backups"] else "（无）"))
    print("== 将写入（reasoning/*.json）==")
    for coll, n in p["write"].items():
        print(f"  {coll}: {n} 条")
    print("提醒：重灌生成新 ObjectId（id = _id 变新），ES 的旧 _id 会全部失配，"
          "之后请跑 `python -m app.sync recreate`。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ingest.py",
        description="把 reasoning/*.json 重灌进 Mongo 权威库（会先 drop 三个集合，破坏性）。",
        epilog="只想同步 ES、不动 Mongo：python -m app.sync full",
    )
    parser.add_argument("--yes", action="store_true", help="显式确认执行破坏性清库 + 重灌")
    parser.add_argument("--dry-run", action="store_true", help="只打印将清空/将写入的条数，不动库")
    args = parser.parse_args(argv)

    try:
        db = get_db()

        if args.dry_run:
            print_plan(plan(db))
            print("[预演] 未动数据库")
            return 0

        if not args.yes:
            p = plan(db)
            print(f"[拒绝] 未执行任何操作：本脚本会 drop {'/'.join(p['drop'])} 三个集合、"
                  f"删除失效备份 {p['backups'] or '（无）'}，再按 reasoning/*.json 重灌（新 ObjectId "
                  f"会让 ES 旧 _id 全部失配）。确认执行请加 --yes；先看影响请用 --dry-run。",
                  file=sys.stderr)
            print_plan(p)
            return 1

        print_plan(plan(db))
        print("== 执行 ==")
        clear_all(db)
        for name in ENTITIES:
            print(f"{ENTITIES[name]['collection']}: count = {ingest_entity(db, name)}")
        print("[完成] Mongo 已重灌；接着跑 `python -m app.sync recreate` 让 ES 与新的 _id 对齐。")
        return 0
    finally:
        close()


if __name__ == "__main__":
    raise SystemExit(main())

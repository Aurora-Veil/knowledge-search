"""把 reasoning/*.json 当种子导入 Mongo：按 (project_id, oirf_id) 增量 upsert。

设计取舍（都是踩过坑之后的结论）：
- **默认只增改、不删**（`--prune` 才删 Mongo 里种子已没有的），所以常规导入不需要 `--yes`。
- **内容未变的文档不写库、也不推 ES** → 可反复跑，重复跑几乎瞬时（幂等）。
- **_id 不再被打乱** → 导入后不需要再跑 `recreate`；ES 侧只把"变动过的那几条/被删的那几条"
  收集成 actions，一次 bulk + 结尾刷新一次（实测逐条推送慢 112 倍：397 条 26.85s vs 0.24s）。
- `--reset` 保留旧的"清空重灌"能力（会重建 ObjectId），必须显式 `--yes`，
  并且会自动把 ES 三索引一并重建重灌，避免"Mongo 新的、ES 旧的"半截状态。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from pymongo import ASCENDING

from ..config import COLLECTION_BY_TYPE, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import resolve_db, resolve_es
from . import admin, full

SEED_DIR = Path(__file__).resolve().parents[2] / "reasoning"

SEED_FILE: dict[str, str] = {
    "source": "source.json",
    "evidence": "evidence.json",
    "viewpoint": "viewpoint.json",
}
SEED_KEY: dict[str, str] = {
    "source": "sources",
    "evidence": "evidence",
    "viewpoint": "viewpoints",
}

# 旧的复合主键迁移备份，id 模型已变更、已失效，--reset 时一并删除
STALE_BACKUPS = ("_bk_sources", "_bk_evidence", "_bk_viewpoints")

# 种子文件里的 id 是生成期的 int，一律丢弃/忽略（id 模型：id = _id，由 Mongo 生成）
_ID_KEYS = ("_id", "id")


def read_seed(type_: str) -> list[dict[str, Any]]:
    """读种子文件（丢掉生成期的 id）。"""
    if type_ not in SEED_FILE:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(SEED_FILE)})")
    with (SEED_DIR / SEED_FILE[type_]).open(encoding="utf-8") as f:
        docs = json.load(f)[SEED_KEY[type_]]
    for d in docs:
        d.pop("id", None)
    return docs


def _ensure_query_indexes(coll) -> None:
    """查询支持索引（唯一性交给 _id，无需 unique）。"""
    coll.create_index([("project_id", ASCENDING)])
    coll.create_index([("oirf_id", ASCENDING)])
    coll.create_index([("project_id", ASCENDING), ("oirf_id", ASCENDING)])


def _key(doc: Mapping[str, Any]) -> tuple[Any, Any]:
    return doc.get("project_id"), doc.get("oirf_id")


def _seed_fields_match(seed: Mapping[str, Any], stored: Mapping[str, Any]) -> bool:
    """只比种子声明的字段：Mongo 侧的额外字段（含 _id/id）不参与比较、也不会被删。"""
    return all(stored.get(k) == v for k, v in seed.items() if k not in _ID_KEYS)


def plan_type(type_: str, db=None, prune: bool = False) -> dict[str, Any]:
    """算"将新增 / 将更新 / 未变 / 将删除"，不写任何东西。"""
    coll = resolve_db(db)[COLLECTION_BY_TYPE[type_]]
    seeds = read_seed(type_)
    stored = {_key(d): d for d in coll.find({})}

    insert: list[dict[str, Any]] = []
    update: list[dict[str, Any]] = []
    unchanged = 0
    for seed in seeds:
        cur = stored.get(_key(seed))
        if cur is None:
            insert.append(seed)
        elif _seed_fields_match(seed, cur):
            unchanged += 1
        else:
            update.append(seed)

    seed_keys = {_key(s) for s in seeds}
    extra = [d for k, d in stored.items() if k not in seed_keys]

    return {
        "type": type_, "collection": COLLECTION_BY_TYPE[type_], "index": INDEX_BY_TYPE[type_],
        "seed": len(seeds), "stored": len(stored), "unchanged": unchanged,
        "insert": insert, "update": update, "extra": extra,
        "prune": extra if prune else [],
    }


def plan(types: Iterable[str] | None = None, db=None, prune: bool = False) -> list[dict[str, Any]]:
    return [plan_type(t, db=db, prune=prune) for t in (types or OBJECT_TYPES)]


def apply_type(plan_: Mapping[str, Any], db=None) -> dict[str, Any]:
    """落库：insert（Mongo 生成 _id 并回写 id = _id）/ update（$set，保留 _id 与 Mongo 侧额外字段）/ prune 删除。

    返回里带上"变动后的完整文档"与"被删的 _id"，供随后的 ES 推送直接用，避免再查一遍 Mongo。
    """
    coll = resolve_db(db)[plan_["collection"]]
    if plan_["insert"] or plan_["update"]:
        _ensure_query_indexes(coll)

    changed: list[dict[str, Any]] = []
    removed_ids: list[str] = []

    for seed in plan_["insert"]:
        res = coll.insert_one(dict(seed))
        coll.update_one({"_id": res.inserted_id}, {"$set": {"id": res.inserted_id}})  # id = _id
        stored = coll.find_one({"_id": res.inserted_id})
        if stored:
            changed.append(stored)

    for seed in plan_["update"]:
        key = {"project_id": seed.get("project_id"), "oirf_id": seed.get("oirf_id")}
        coll.update_one(key, {"$set": {k: v for k, v in seed.items() if k not in _ID_KEYS}})
        stored = coll.find_one(key)
        if stored:
            changed.append(stored)

    for doc in plan_["prune"]:
        coll.delete_one({"_id": doc["_id"]})
        removed_ids.append(str(doc["_id"]))

    return {
        "type": plan_["type"], "collection": plan_["collection"], "index": plan_["index"],
        "inserted": len(plan_["insert"]), "updated": len(plan_["update"]), "deleted": len(plan_["prune"]),
        "changed": changed, "removed_ids": removed_ids,
    }


def push_type(applied: Mapping[str, Any], es=None) -> dict[str, Any]:
    """把变动过/被删的文档一次 bulk 推给 ES（index + delete 混用），结尾刷新一次。"""
    es = resolve_es(es)
    type_ = applied["type"]
    actions = [full.doc_action(type_, d) for d in applied["changed"]]
    actions += [full.delete_action(type_, i) for i in applied["removed_ids"]]
    out = full.write_actions(actions, es=es)
    if actions:
        es.indices.refresh(index=applied["index"])
    return {"type": type_, "index": applied["index"], "pushed": len(actions), **out}


def reset(db=None, es=None, sync: bool = True) -> dict[str, Any]:
    """旧的"清空重灌"：drop Mongo 三集合（+ 失效备份）→ 按种子重灌 → （默认）重建 ES 并重灌。

    会重建 ObjectId，所以 ES 必须跟着重建，否则旧 _id 全成孤儿。
    """
    db = resolve_db(db)
    es = resolve_es(es)

    for t in OBJECT_TYPES:
        db.drop_collection(COLLECTION_BY_TYPE[t])
    for bk in STALE_BACKUPS:
        if bk in db.list_collection_names():
            db.drop_collection(bk)

    loaded: dict[str, int] = {}
    for t in OBJECT_TYPES:
        coll = db[COLLECTION_BY_TYPE[t]]
        _ensure_query_indexes(coll)
        for seed in read_seed(t):
            res = coll.insert_one(dict(seed))
            coll.update_one({"_id": res.inserted_id}, {"$set": {"id": res.inserted_id}})
        loaded[t] = coll.count_documents({})

    out: dict[str, Any] = {"loaded": loaded, "es": None, "recreated": []}
    if sync:
        for t in OBJECT_TYPES:
            admin.recreate(INDEX_BY_TYPE[t], t, es)
            out["recreated"].append(INDEX_BY_TYPE[t])
        out["es"] = full.sync_all(es=es, db=db)
    return out


def mongo_counts(db=None) -> dict[str, int]:
    db = resolve_db(db)
    return {t: db[COLLECTION_BY_TYPE[t]].count_documents({}) for t in OBJECT_TYPES}


__all__ = [
    "SEED_DIR", "SEED_FILE", "SEED_KEY", "STALE_BACKUPS", "read_seed",
    "plan_type", "plan", "apply_type", "push_type", "reset", "mongo_counts",
]

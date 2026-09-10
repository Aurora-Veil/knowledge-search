"""
Compare ES and Mongo _id sets, listing orphans and missing 
"""
from __future__ import annotations

from typing import Any, Sequence

from bson import ObjectId
from elasticsearch import NotFoundError
from elasticsearch.helpers import scan

from ..config import COLLECTION_BY_TYPE, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import resolve_db, resolve_es
from . import one

SCAN_SIZE = 1000


def mongo_ids(type_: str, db=None) -> set[str]:
    """Mongo _id"""
    coll = resolve_db(db)[COLLECTION_BY_TYPE[type_]]
    return {str(d["_id"]) for d in coll.find({}, {"_id": 1})}


def es_ids(type_: str, es=None) -> set[str]:
    """ES _id"""
    body = {"query": {"match_all": {}}, "_source": False}
    es = resolve_es(es)
    return {h["_id"] for h in scan(es, index=INDEX_BY_TYPE[type_], query=body, size=SCAN_SIZE)}


def compare_type(type_: str, es=None, db=None) -> dict[str, Any]:
    """ Single type: compare Mongo _id set and ES _id set """
    es = resolve_es(es)
    index = INDEX_BY_TYPE[type_]
    if not es.indices.exists(index=index):
        return {"type": type_, "index": index, "index_exists": False,
                "mongo": len(mongo_ids(type_, db)), "es": 0, "orphans": [], "missing": []}
    m, e = mongo_ids(type_, db), es_ids(type_, es)
    return {"type": type_, "index": index, "index_exists": True,
            "mongo": len(m), "es": len(e),
            "orphans": sorted(e - m), "missing": sorted(m - e)}


def compare(types: Sequence[str] = OBJECT_TYPES, es=None, db=None) -> list[dict[str, Any]]:
    return [compare_type(t, es, db) for t in types]


def drift_count(reports: Sequence[dict[str, Any]]) -> int:
    return sum(len(r["orphans"]) + len(r["missing"]) for r in reports)


def fix(reports: Sequence[dict[str, Any]], es=None, db=None) -> dict[str, Any]:
    """
    Delete orphans from ES, reindex missing from Mongo to ES.
    Return dict with counts of deleted, reindexed, errors, skipped.
    """
    es = resolve_es(es)
    db = resolve_db(db)
    deleted = reindexed = 0
    errors: list[str] = []
    skipped: list[str] = []

    for r in reports:
        if not r["index_exists"]:
            skipped.append(f"{r['index']}：索引不存在，先跑 init/recreate 建索引")
            continue
        index, t = r["index"], r["type"]

        for i in r["orphans"]:
            try:
                es.delete(index=index, id=i)
                deleted += 1
            except NotFoundError:
                pass

        for i in r["missing"]:
            doc = db[COLLECTION_BY_TYPE[t]].find_one({"_id": ObjectId(i)})
            if doc is None:
                errors.append(f"{t} {i}：Mongo 侧已消失（对账期间被删）")
                continue
            one.sync_one(doc["project_id"], doc["oirf_id"], t, db=db, es=es)
            reindexed += 1

        es.indices.refresh(index=index)

    return {"deleted": deleted, "reindexed": reindexed, "errors": errors, "skipped": skipped}


__all__ = ["SCAN_SIZE", "mongo_ids", "es_ids", "compare_type", "compare", "drift_count", "fix"]

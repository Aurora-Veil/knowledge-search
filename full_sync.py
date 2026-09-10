# full_sync.py —— 用 mapping 建索引，并 Mongo -> ES

import json
import os
from datetime import datetime

from pymongo import MongoClient
from bson import ObjectId
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

MONGO_URI = "mongodb://localhost:27017"
DB_NAME   = "knowledge_db"
ES_URL    = "http://localhost:9200"
BASE      = os.path.dirname(os.path.abspath(__file__))
MAPPING   = os.path.join(BASE, "mapping")

INDICES = {
    "source":    {"index": "knowledge_source",    "mapping": "source_mapping.json",    "collection": "sources"},
    "evidence":  {"index": "knowledge_evidence",  "mapping": "evidence_mapping.json",  "collection": "evidence"},
    "viewpoint": {"index": "knowledge_viewpoint", "mapping": "viewpoint_mapping.json", "collection": "viewpoints"},
}


def _jsonable(v):
    """ BSON -> JSON """
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def load_mapping(name: str) -> dict:
    with open(os.path.join(MAPPING, INDICES[name]["mapping"]), encoding="utf-8") as f:
        return json.load(f)


def ensure_indices(es, name: str) -> None:
    cfg = INDICES[name]
    if es.indices.exists(index=cfg["index"]):
        print(f"  index {cfg['index']} exists, skip create")
        return
    body = load_mapping(name)
    es.indices.create(
        index=cfg["index"],
        settings=body.get("settings"),
        mappings=body.get("mappings"),
    )
    print(f"  created {cfg['index']}")


def full_sync(es, mongo, name: str) -> int:
    cfg = INDICES[name]
    coll = mongo[cfg["collection"]]

    def actions():
        for d in coll.find({}):
            src = _jsonable(d)            # ObjectId -> str
            sid = src.pop("_id", None) or src["id"]   # ES 文档 id = ObjectId str
            yield {"_index": cfg["index"], "_id": str(sid), "_source": src}

    bulk(es, actions(), chunk_size=500, raise_on_error=False)
    return coll.count_documents({})


def main() -> None:
    mongo = MongoClient(MONGO_URI)[DB_NAME]
    es = Elasticsearch(ES_URL)
    try:
        print("== ensure indices ==")
        for name in INDICES:
            ensure_indices(es, name)

        print("== full sync ==")
        for name in INDICES:
            cfg = INDICES[name]
            n = full_sync(es, mongo, name)
            print(f"  {cfg['index']}: synced {n} docs")
    finally:
        es.close()


if __name__ == "__main__":
    main()

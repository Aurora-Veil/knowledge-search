# scripts/full_sync.py —— Mongo -> ES（含向量）。索引结构由 init_es_structure.py 建。

import sys
import time
from datetime import datetime
from pathlib import Path

# repo root on sys.path, so this runs from any working directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pymongo import MongoClient
from bson import ObjectId
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import DB_NAME, MONGO_URI, es_auth, es_hosts
from embedding.encoder import Encoder, resolve_snapshot
from embedding.spec import MODEL, build_text, text_hash
from scripts.init_es_structure import require

INDICES = {
    "source":    {"index": "knowledge_source",    "collection": "sources"},
    "evidence":  {"index": "knowledge_evidence",  "collection": "evidence"},
    "viewpoint": {"index": "knowledge_viewpoint", "collection": "viewpoints"},
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


def _embed(name: str, docs: list[dict], encoder: Encoder) -> None:
    """
    Attach the vector and its provenance to each document, in place.

    """
    texts = [build_text(src, name) for src in docs]
    todo = [i for i, t in enumerate(texts) if t]
    if len(todo) != len(texts):
        print(f"  warn: {len(texts) - len(todo)} doc(s) have no vector text")
    if not todo:
        return

    t0 = time.perf_counter()
    vectors = encoder.encode_passages([texts[i] for i in todo])
    rev = resolve_snapshot().name          # the snapshot that actually produced them
    for i, vector in zip(todo, vectors):
        src = docs[i]
        src["embedding"] = vector
        src["embed_model"] = MODEL["name"]
        src["embed_rev"] = rev
        src["embed_text_hash"] = text_hash(texts[i])
    print(f"  encoded {len(todo)} docs in {time.perf_counter() - t0:.1f}s")


def full_sync(es, mongo, name: str, encoder: Encoder) -> int:
    cfg = INDICES[name]
    coll = mongo[cfg["collection"]]

    docs = []
    for d in coll.find({}):
        src = _jsonable(d)                        # ObjectId -> str
        sid = src.pop("_id", None) or src["id"]    # ES 文档 id = ObjectId str
        docs.append((sid, src))

    # Vectors are built from exactly what gets stored
    _embed(name, [src for _, src in docs], encoder)

    def actions():
        for sid, src in docs:
            yield {"_index": cfg["index"], "_id": str(sid), "_source": src}

    bulk(es, actions(), chunk_size=500, raise_on_error=False)
    return coll.count_documents({})


def main() -> None:
    mongo = MongoClient(MONGO_URI)[DB_NAME]
    es = Elasticsearch(es_hosts(), basic_auth=es_auth())
    try:
        print("== check structure ==")
        for name in INDICES:
            require(es, INDICES[name]["index"])

        print("== full sync ==")
        encoder = Encoder()          # free: the model loads on the first encode
        for name in INDICES:
            cfg = INDICES[name]
            n = full_sync(es, mongo, name, encoder)
            print(f"  {cfg['index']}: synced {n} docs")
    finally:
        es.close()


if __name__ == "__main__":
    main()

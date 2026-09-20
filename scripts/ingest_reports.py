# scripts/ingest_reports.py —— example/reports.json -> ES

import argparse
import json
import sys
import time
from pathlib import Path

# repo root on sys.path, so this runs from any working directory
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import es_auth, es_hosts
from embedding.encoder import Encoder, resolve_snapshot
from embedding.spec import MODEL, build_text, text_hash

INDEX = "knowledge_report_index"
MAPPING_PATH = ROOT / "mapping" / "report_mapping.json"
SOURCE_PATH = ROOT / "example" / "reports.json"

TOKEN_LIMIT = 512          # == embedding/fields.json 的 model.max_tokens
ENCODE_CHUNK = 256
BULK_CHUNK = 500
TYPE = "report"


def load_reports(limit: int | None) -> list[dict]:
    with SOURCE_PATH.open(encoding="utf-8") as f:
        reports = json.load(f)["reports"]
    return reports[:limit] if limit else reports


def ensure_index(es: Elasticsearch, recreate: bool) -> None:
    exists = es.indices.exists(index=INDEX)
    if recreate and exists:
        es.indices.delete(index=INDEX)
        print(f"  dropped {INDEX}")
        exists = False
    if exists:
        print(f"  {INDEX} exists, keep mapping")
        return
    body = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    es.indices.create(index=INDEX, settings=body.get("settings"),
                      mappings=body.get("mappings"))
    print(f"  created {INDEX}")


def count_truncated(texts: list[str]) -> int:
    """How many passages the model limit will cut. Needs the tokenizer only."""
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(resolve_snapshot()))
    return sum(1 for t in texts
               if len(tok(t, add_special_tokens=True)["input_ids"]) > TOKEN_LIMIT)


def build_docs(reports: list[dict], encoder: Encoder) -> tuple[list[dict], int]:
    """Attach vector + provenance to each report, in place."""
    texts = [build_text(r, TYPE) for r in reports]

    empty = [i for i, t in enumerate(texts) if not t]
    if empty:
        print(f"  warn: {len(empty)} report(s) have no vector text")

    truncated = count_truncated(texts)
    if truncated:
        print(f"  note: {truncated}/{len(texts)} passage(s) exceed {TOKEN_LIMIT} "
              f"tokens and are truncated (tail not vectorized)")

    todo = [i for i, t in enumerate(texts) if t]
    if not todo:
        return reports, 0

    rev = resolve_snapshot().name          # the snapshot that actually produced them
    t0 = time.perf_counter()
    done = 0
    for start in range(0, len(todo), ENCODE_CHUNK):
        batch = todo[start:start + ENCODE_CHUNK]
        vectors = encoder.encode_passages([texts[i] for i in batch])
        for i, vector in zip(batch, vectors):
            src = reports[i]
            src["embedding"] = vector
            src["embed_model"] = MODEL["name"]
            src["embed_rev"] = rev
            src["embed_text_hash"] = text_hash(texts[i])
        done += len(batch)
        print(f"  encoded {done}/{len(todo)}  ({time.perf_counter() - t0:.1f}s)")
    return reports, len(todo)


def write(es: Elasticsearch, reports: list[dict]) -> int:
    def actions():
        for r in reports:
            yield {"_index": INDEX, "_id": r["report_id"], "_source": r}

    ok, errors = bulk(es, actions(), chunk_size=BULK_CHUNK,
                      raise_on_error=False, stats_only=False)
    print(f"  bulk: {ok} ok, {len(errors)} failed")
    for e in errors[:5]:
        print(f"    {e}")
    return len(errors)


def main() -> int:
    ap = argparse.ArgumentParser(description="report json -> elasticsearch")
    ap.add_argument("--recreate", action="store_true",
                    help="drop and recreate the index (full re-embed)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only ingest the first N reports (smoke test)")
    args = ap.parse_args()

    es = Elasticsearch(es_hosts(), basic_auth=es_auth())
    try:
        print("== ensure index ==")
        ensure_index(es, args.recreate)

        reports = load_reports(args.limit)
        print(f"== ingest {len(reports)} reports from {SOURCE_PATH.name} ==")

        encoder = Encoder()                # free: the model loads on the first encode
        reports, embedded = build_docs(reports, encoder)

        failed = write(es, reports)
        es.indices.refresh(index=INDEX)
        print(f"== done: index count = {es.count(index=INDEX)['count']}, "
              f"embedded = {embedded}, failed = {failed} ==")
        return 1 if failed else 0
    finally:
        es.close()


if __name__ == "__main__":
    raise SystemExit(main())

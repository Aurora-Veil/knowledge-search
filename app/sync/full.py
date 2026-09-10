"""全量灌：Mongo 三集合 → ES 三索引（分块 bulk，解析真实成功/失败计数）。

约定：计数取 bulk 返回值而非 count_documents；失败时调用方以非 0 退出码收场。
"""
from __future__ import annotations

from typing import Any, Iterator

from elasticsearch.helpers import bulk

from ..config import COLLECTION_BY_TYPE, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import resolve_db, resolve_es
from ..serializers import to_jsonable

CHUNK_SIZE = 500
ERROR_LIMIT = 5  # 只打印前几条失败原因；触发上限，计数不受影响


def iter_actions(type_: str, db) -> Iterator[dict[str, Any]]:
    """把一个集合摊成 bulk actions：ES _id = str(Mongo _id)，天然幂等 upsert。"""
    coll = db[COLLECTION_BY_TYPE[type_]]
    index = INDEX_BY_TYPE[type_]
    for doc in coll.find({}):
        src = to_jsonable(doc)
        sid = src.pop("_id", None) or src.get("id")
        yield {"_index": index, "_id": str(sid), "_source": src}


def _error_lines(errors: list[Any], limit: int = ERROR_LIMIT) -> list[str]:
    """把 bulk 返回的失败项摊成人可读行（操作 / 索引 / _id / status / 原因）。"""
    lines: list[str] = []
    for e in errors[:limit]:
        if not isinstance(e, dict) or not e:
            lines.append(str(e))
            continue
        op, info = next(iter(e.items()))
        info = info or {}
        err = info.get("error") or {}
        reason = err.get("reason") or err.get("type") or info.get("result")
        lines.append(f"{op} {info.get('_index')}/{info.get('_id')} status={info.get('status')} {reason}")
    return lines


def count_source(type_: str, db=None) -> int:
    """该类型在 Mongo 里的条数（供 dry-run 预告"将写入多少条"，不参与真实计数）。"""
    db = resolve_db(db)
    return db[COLLECTION_BY_TYPE[type_]].count_documents({})


def sync_type(type_: str, es=None, db=None, chunk_size: int = CHUNK_SIZE) -> dict[str, Any]:
    """灌一个类型，返回 {index, ok, failed, error_lines}；ok/failed 取自 bulk 返回值。"""
    es = resolve_es(es)
    db = resolve_db(db)
    ok, errors = bulk(
        es, iter_actions(type_, db), chunk_size=chunk_size,
        raise_on_error=False, stats_only=False,
    )
    errors = list(errors or [])
    return {
        "index": INDEX_BY_TYPE[type_],
        "ok": int(ok),
        "failed": len(errors),
        "error_lines": _error_lines(errors),
    }


def sync_all(es=None, db=None, chunk_size: int = CHUNK_SIZE, refresh: bool = True) -> dict[str, dict[str, Any]]:
    """灌三个类型；refresh=True 时结束后刷新索引，使随后查到的 _count 与本次报数一致。"""
    es = resolve_es(es)
    out = {t: sync_type(t, es=es, db=db, chunk_size=chunk_size) for t in OBJECT_TYPES}
    if refresh:
        es.indices.refresh(index=[INDEX_BY_TYPE[t] for t in OBJECT_TYPES])
    return out


__all__ = ["CHUNK_SIZE", "iter_actions", "count_source", "sync_type", "sync_all"]

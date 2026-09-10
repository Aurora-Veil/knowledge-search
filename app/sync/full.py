"""全量灌：Mongo 三集合 → ES 三索引（分块 bulk，解析真实成功/失败计数）。

约定：计数取 bulk 返回值而非 count_documents；失败时调用方以非 0 退出码收场。
"""
from __future__ import annotations

from typing import Any, Iterable, Iterator, Mapping, Sequence

from elasticsearch.helpers import bulk

from ..config import COLLECTION_BY_TYPE, INDEX_BY_TYPE, OBJECT_TYPES
from ..db import resolve_db, resolve_es
from ..serializers import to_jsonable

CHUNK_SIZE = 500
ERROR_LIMIT = 5  # 只打印前几条失败原因；触发上限，计数不受影响


def doc_action(type_: str, doc: Mapping[str, Any]) -> dict[str, Any]:
    """一个文档 → 一条 bulk index action（ES _id = str(Mongo _id)，天然幂等 upsert）。"""
    src = to_jsonable(doc)
    sid = src.pop("_id", None) or src.get("id")
    return {"_index": INDEX_BY_TYPE[type_], "_id": str(sid), "_source": src}


def delete_action(type_: str, doc_id: str) -> dict[str, Any]:
    """一条 bulk delete action（用于对象已从 Mongo 删除的场景）。"""
    return {"_op_type": "delete", "_index": INDEX_BY_TYPE[type_], "_id": doc_id}


def iter_actions(type_: str, db=None) -> Iterator[dict[str, Any]]:
    """把一个集合摊成 bulk actions（流式，不整体载入内存）。"""
    coll = resolve_db(db)[COLLECTION_BY_TYPE[type_]]
    for doc in coll.find({}):
        yield doc_action(type_, doc)


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


def _bulk(actions: Iterable[dict[str, Any]], es, chunk_size: int) -> dict[str, Any]:
    ok, errors = bulk(
        es, actions, chunk_size=chunk_size, raise_on_error=False, stats_only=False,
    )
    errors = list(errors or [])
    return {"ok": int(ok), "failed": len(errors), "error_lines": _error_lines(errors)}


def write_actions(actions: Sequence[dict[str, Any]], es=None, chunk_size: int = CHUNK_SIZE) -> dict[str, Any]:
    """批量写入给定的 actions（index / delete 可混用），返回真实成功/失败计数。

    调用方负责写完后 refresh（bulk 本身不刷新）。空列表直接返回零计数 ——
    helpers.bulk 对空 actions 会抛 ValueError，所以这里先挡住。
    """
    if not actions:
        return {"ok": 0, "failed": 0, "error_lines": []}
    return _bulk(list(actions), resolve_es(es), chunk_size)


def count_source(type_: str, db=None) -> int:
    """该类型在 Mongo 里的条数（供 dry-run 预告"将写入多少条"，不参与真实计数）。"""
    db = resolve_db(db)
    return db[COLLECTION_BY_TYPE[type_]].count_documents({})


def sync_type(type_: str, es=None, db=None, chunk_size: int = CHUNK_SIZE) -> dict[str, Any]:
    """灌一个类型，返回 {index, ok, failed, error_lines}；ok/failed 取自 bulk 返回值。"""
    out = _bulk(iter_actions(type_, db=db), resolve_es(es), chunk_size)
    return {"index": INDEX_BY_TYPE[type_], **out}


def sync_all(es=None, db=None, chunk_size: int = CHUNK_SIZE, refresh: bool = True) -> dict[str, dict[str, Any]]:
    """灌三个类型；refresh=True 时结束后刷新索引，使随后查到的 _count 与本次报数一致。"""
    es = resolve_es(es)
    out = {t: sync_type(t, es=es, db=db, chunk_size=chunk_size) for t in OBJECT_TYPES}
    if refresh:
        es.indices.refresh(index=[INDEX_BY_TYPE[t] for t in OBJECT_TYPES])
    return out


__all__ = [
    "CHUNK_SIZE", "doc_action", "delete_action", "iter_actions", "write_actions",
    "count_source", "sync_type", "sync_all",
]

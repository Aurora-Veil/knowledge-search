"""
检索缓存键。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Mapping

PREFIX = "oirf:report:"

_DIGEST_CHARS = 32
_TERMS = ("report_id", "layout", "industry")
_DAYS = ("publish_date_from", "publish_date_to")


def _terms(value: Any) -> list[str]:
    vals = value if isinstance(value, (list, tuple)) else [value]
    return sorted({str(v) for v in vals})


def _day(value: Any) -> str:
    return value.isoformat() if isinstance(value, date) else str(value)


def canonical(p: Mapping[str, Any], page: int, size: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "q": str(p.get("q") or "").strip(),
        "page": page,
        "size": size,
        "mode": p.get("mode") or "or",
        "time_weight": float(p.get("time_weight") or 0.0),
        "highlight": p.get("highlight", True) is not False,
    }

    for name in _TERMS:
        if p.get(name):
            body[name] = _terms(p[name])
    for name in _DAYS:
        if p.get(name):
            body[name] = _day(p[name])

    return body


def cache_key(p: Mapping[str, Any], page: int, size: int) -> str:
    text = json.dumps(canonical(p, page, size), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)
    return PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


__all__ = ["PREFIX", "canonical", "cache_key"]

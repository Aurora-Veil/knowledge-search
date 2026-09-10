from __future__ import annotations

from typing import Any, Iterable

# different index ranking

Pool = tuple[str, list[dict[str, Any]], float | None]  # (type, hits, max_score)
Fused = tuple[float, float, dict[str, Any], str]  # (norm, raw, hit, type)


def _norm(raw: float, max_score: float | None) -> float:
    return (raw / max_score) if max_score else 0.0


def fuse(pools: Iterable[Pool], page: int, size: int) -> list[Fused]:
    """normalize and fuse hits from different pools"""
    pooled: list[Fused] = []
    for type_, hits, max_score in pools:
        for h in hits:
            raw = h.get("_score") or 0.0
            pooled.append((_norm(raw, max_score), raw, h, type_))

    pooled.sort(key=lambda x: -x[0])
    start = (page - 1) * size
    return pooled[start : start + size]


__all__ = ["fuse"]

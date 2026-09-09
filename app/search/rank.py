from __future__ import annotations

from typing import Any, Iterable

# 跨索引不能直接比原始 BM25 _score：索引规模 N 不同使 idf 标尺不同（evidence 349 条 vs source/viewpoint 24 条），
# 故用 max-score 归一化（score/max_score → 0~1）抹平标尺再合并。调 BM25 的 k1/b 治不了（只管 tf/长度，不碰 idf）。

Pool = tuple[str, list[dict[str, Any]], float | None]  # (type, hits, max_score)
Fused = tuple[float, float, dict[str, Any], str]  # (norm, raw, hit, type)


def _norm(raw: float, max_score: float | None) -> float:
    return (raw / max_score) if max_score else 0.0  # 纯过滤(无 q)时 max_score 为 0/None → 0


def fuse(pools: Iterable[Pool], page: int, size: int) -> list[Fused]:
    """归一化降序合并各索引命中，取全局第 page 页。"""
    pooled: list[Fused] = []
    for type_, hits, max_score in pools:
        for h in hits:
            raw = h.get("_score") or 0.0
            pooled.append((_norm(raw, max_score), raw, h, type_))

    pooled.sort(key=lambda x: -x[0])
    start = (page - 1) * size
    return pooled[start : start + size]


__all__ = ["fuse"]

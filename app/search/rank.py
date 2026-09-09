"""type=all 的多索引融合（纯函数，无 ES 依赖，便于测试）。

跨索引不能直接比原始 BM25 `_score`：不同索引规模 N 使 idf 标尺不同（evidence 349 条 vs source/viewpoint 24 条，
evidence identity.name 的 idf≈4.15 vs source≈1.97，而 boost/tf 相同），字段/权重拓扑亦异。
故用 **max-score 归一化**（score/max_score → 0~1）抹平标尺再合并排序。

调 BM25 的 `k1/b` 治不了——只管 tf 饱和/长度归一，不碰 idf。参见 docs/search-api-design.md §5.1。
"""
from __future__ import annotations

from typing import Any, Iterable

# (type, hits, max_score) 每个元素：一个索引的命中列表及其最大分
Pool = tuple[str, list[dict[str, Any]], float | None]
Fused = tuple[float, float, dict[str, Any], str]  # (norm, raw, hit, type)


def _norm(raw: float, max_score: float | None) -> float:
    """归一化到 0~1；max_score 缺失/为 0（纯过滤无 q、score 全 0）时给 0。"""
    return (raw / max_score) if max_score else 0.0


def fuse(pools: Iterable[Pool], page: int, size: int) -> list[Fused]:
    """把各索引的命中按归一化分降序合并，取全局第 page 页。

    纯过滤（无 q）时各分全为 0，归并根据 pool 传入顺序稳定排序（索引序），可接受。
    """
    pooled: list[Fused] = []
    for type_, hits, max_score in pools:
        for h in hits:
            raw = h.get("_score") or 0.0
            pooled.append((_norm(raw, max_score), raw, h, type_))

    pooled.sort(key=lambda x: -x[0])  # 归一化分降序
    start = (page - 1) * size
    return pooled[start : start + size]


__all__ = ["fuse"]

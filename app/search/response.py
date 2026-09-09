"""把 ES 命中整形为轻卡片（§5.1 响应）。

入参是 ES 命中（hit）：`_source` 已被 query.py 的 source 白名单裁剪过 —— 只含可搜/可筛字段 + 识别键，
不含未映射长文本（raw_texts/notes/summary/content/explanation/narrative/*_reason/lifecycle 等），
那些走 /objects 回 Mongo 取。
"""
from __future__ import annotations

from typing import Any

# 卡片里透传的子对象（按类型在 query.py 白名单里裁剪过，这里直接透传）
_CARD_FIELDS = ("identity", "presentation", "reasoning", "experience", "responsibility")


def hit_to_card(hit: dict[str, Any], object_type: str) -> dict[str, Any]:
    """一条 hit → 轻卡片 dict。

    - 识别键置顶：id(=ES _id=Mongo id)、object_type、project_id、oirf_id、score
    - 之后是各卡片字段（identity/presentation/reasoning/experience/responsibility）——已是白名单内容
    - `highlight` / `inner_hits` 原样附带（命中看点 / nested 命中的那个元素）
    """
    src = hit.get("_source") or {}

    card: dict[str, Any] = {
        "id": src.get("id") or hit.get("_id"),
        "object_type": object_type,
        "project_id": src.get("project_id"),
        "oirf_id": src.get("oirf_id"),
        "score": hit.get("_score"),
    }

    for f in _CARD_FIELDS:
        if f in src and src[f] is not None:
            card[f] = src[f]

    if "highlight" in hit:
        card["highlight"] = hit["highlight"]
    if "inner_hits" in hit:
        # 保留命中的那个数组元素 _source（含未映射字段，如步骤的 to/operator）
        card["inner_hits"] = hit["inner_hits"]

    return card

"""核心：构造发给 Elasticsearch 的搜索语句本体。

一切都在这里拼装 ES 查询 DSL；路由层只接参、search.py 只发请求，都不直接拼 DSL。

设计来源：docs/search-api-design.md §5.1 / §5.1.1。
- 全文：`multi_match`（type:best_fields, analyzer: ik_smart），按类型给字段^权重（只影响排序，不影响召回）。
- 精确筛选：`term`/`terms` 打在 keyword 字段，进 `bool.filter`（不计分、可缓存）。
- `nested`（responsibility / viewpoint 的 reasoning.steps）→ 用 nested 查询包住 + `inner_hits` 让调用方"看到命中的那一条"。
- 字段路径与 mapping 一一核对过（source/evidence/viewpoint 三份 mapping）。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from ..config import OBJECT_TYPES

# ---------------------------------------------------------------------------
# 常量：索引无关的权重 / 命中卡片需带回的 _source 字段
# ---------------------------------------------------------------------------

# 各类型全文检索字段（field^boost）。build_query(multi_match) 用；权重仅影响排序。
WEIGHTS: dict[str, list[str]] = {
    "source": [
        "identity.name^3",
        "presentation.title^2",
        "presentation.publisher.text^2",
    ],
    "evidence": [
        "identity.name^3",
        "presentation.subject.text^2",
        "presentation.indicator^2",
        "presentation.value^2",
    ],
    "viewpoint": [
        "presentation.name^3",
        "identity.name^2.5",
        "experience.name^2",
    ],
}

# 命中卡片需带回的 _source 字段（§5.1 响应：识别键 + 可搜/可筛字段；不含未映射长文本，
# 纯展示长文本如 raw_texts/notes/summary/content/explanation/*_reason/lifecycle 由 /objects 回 Mongo 取）。
# 注意：全文检索若用到 `.text` 子字段（subject.text/publisher.text），这里必须带对应基字段（presentation.subject/publisher），
# 否则 highlight 无从取原文。
_SOURCE_COMMON = [
    "id",
    "project_id",
    "oirf_id",
    "identity.name",
    "identity.object_type",
    "identity.status",
]

_SOURCE_BY_TYPE: dict[str, list[str]] = {
    "source": _SOURCE_COMMON
    + [
        "presentation.type",
        "presentation.title",
        "presentation.uri",
        "presentation.publisher",
        "presentation.rights",
        "experience.level",
        "experience.label",
        "experience.confidence_level",
        "responsibility",
    ],
    "evidence": _SOURCE_COMMON
    + [
        "presentation.subject",
        "presentation.type",
        "presentation.source_type",
        "presentation.industry",
        "presentation.indicator",
        "presentation.value",
        "presentation.period",
        "presentation.region",
        "presentation.unit",
        "reasoning.source_ids",
        "experience.confidence_level",
        "experience.original_publish",
        "responsibility",
    ],
    "viewpoint": _SOURCE_COMMON
    + [
        "presentation.name",
        "presentation.type",
        "experience.name",
        "experience.applicable_scenario",
        "experience.claim_type",
        "experience.cross_validation_mode",
        "reasoning.steps",
        "responsibility",
    ],
}


# ---------------------------------------------------------------------------
# 查询子句构造原语
# ---------------------------------------------------------------------------


def _term(field: str, value: Any) -> dict[str, Any]:
    """单值精确匹配。keyword 字段存的是字符串，数字值转 str 保证命中。"""
    return {"term": {field: str(value)}}


def _terms(field: str, values: Any) -> dict[str, Any]:
    """多值精确匹配（terms）。传列表或多元素，单值亦可。"""
    if isinstance(values, (list, tuple)):
        vals = [str(v) for v in values]
    else:
        vals = [str(values)]
    return {"terms": {field: vals}}


def _nested(path: str, inner: Mapping[str, Any]) -> dict[str, Any]:
    """nested 查询：包一层走 path 下的数组，并带 inner_hits 返回命中的那个元素（精确其 _source）。"""
    return {"nested": {"path": path, "query": dict(inner), "inner_hits": {"_source": True}}}


# ---------------------------------------------------------------------------
# 精确筛选（filter）子句 —— 按类型感知，打在 keyword 字段
# ---------------------------------------------------------------------------


def build_filters(type_: str, p: Mapping[str, Any]) -> list[dict[str, Any]]:
    """按类型组装 bool.filter 子句列表。type_ 必须为具体类型（source/evidence/viewpoint），
    type=all 由 search.py 对每个索引分别调用（各自只加其字段表里有的子句）。

    §5.1.1 关键歧义：`source_ids` 在 evidence 是扁平 keyword（reasoning.source_ids），
    在 viewpoint 是嵌套（reasoning.steps.source_ids）；同一入参按 type_ 映射成不同查询。
    """
    f: list[dict[str, Any]] = []

    # —— 共性 ——
    project_id = p.get("project_id")
    if project_id is not None:
        f.append(_term("project_id", project_id))
    if p.get("status"):
        f.append(_term("identity.status", p["status"]))
    if p.get("presentation_type"):
        f.append(_term("presentation.type", p["presentation_type"]))  # 三类型都有 presentation.type

    # —— evidence（及 type=all 时对 evidence 索引的调用）——
    if type_ == "evidence":
        if p.get("period"):
            f.append(_term("presentation.period.keyword", p["period"]))  # 原字段是 text+standard，必须 .keyword
        if p.get("region"):
            f.append(_term("presentation.region", p["region"]))
        if p.get("industry"):
            f.append(_term("presentation.industry", p["industry"]))
        if p.get("source_type"):
            f.append(_terms("presentation.source_type", p["source_type"]))

    # —— source ——
    if type_ == "source" and p.get("confidence_level"):
        f.append(_term("experience.confidence_level", p["confidence_level"]))

    # —— viewpoint ——
    if type_ == "viewpoint":
        if p.get("claim_type"):
            f.append(_term("experience.claim_type", p["claim_type"]))
        if p.get("applicable_scenario"):
            f.append(_term("experience.applicable_scenario", p["applicable_scenario"]))
        if p.get("cross_validation_mode"):
            f.append(_term("experience.cross_validation_mode", p["cross_validation_mode"]))

    # —— 关联（类型感知）——
    if p.get("source_ids"):
        if type_ == "evidence":
            f.append(_terms("reasoning.source_ids", p["source_ids"]))  # 扁平
        elif type_ == "viewpoint":
            f.append(_nested("reasoning.steps", _terms("reasoning.steps.source_ids", p["source_ids"])))  # 嵌套

    if p.get("evidence_ids") and type_ == "viewpoint":
        f.append(_nested("reasoning.steps", _terms("reasoning.steps.evidence_ids", p["evidence_ids"])))

    if p.get("responsible_role"):
        f.append(_nested("responsibility", _term("responsibility.operator.role", p["responsible_role"])))

    return f


# ---------------------------------------------------------------------------
# 全文检索（must）子句
# ---------------------------------------------------------------------------


def _multi_match(q: str, type_: str) -> dict[str, Any]:
    return {
        "multi_match": {
            "query": q,
            "type": "best_fields",
            "analyzer": "ik_smart",
            "fields": WEIGHTS[type_],
        }
    }


# ---------------------------------------------------------------------------
# 本体：build_query —— 返回可直接 **dict 传给 es.search 的 kwargs
# ---------------------------------------------------------------------------


def build_query(type_: str, p: Mapping[str, Any]) -> dict[str, Any]:
    """组装一个索引的完整搜索参数（query + highlight + source + 分页 + 精确总数）。

    返回的 dict 能直接 `es.search(index=INDEX_BY_TYPE[type_], **build_query(...))`。
    """
    if type_ not in WEIGHTS:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(WEIGHTS)})")

    must: list[dict[str, Any]] = []
    q = p.get("q")
    if q:  # 空 q = 仅过滤
        must.append(_multi_match(q, type_))

    filters = build_filters(type_, p)

    query: dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters

    # 高亮：打在同一类型 multi_match 的字段上，pre/post 用 <em>…</em>
    highlight_fields = {f.split("^", 1)[0]: {} for f in WEIGHTS[type_]}
    highlight = {
        "pre_tags": ["<em>"],
        "post_tags": ["</em>"],
        "fields": highlight_fields,
    }

    page = max(int(p.get("page", 1)), 1)
    size = max(int(p.get("size", 20)), 1)

    body: dict[str, Any] = {
        "query": query,
        "highlight": highlight,
        "source": _SOURCE_BY_TYPE[type_],
        "from_": (page - 1) * size,
        "size": size,
        "track_total_hits": True,
    }

    # §5.1：用户在请求里可关掉高亮（默认开）
    if p.get("highlight", True) is False:
        body.pop("highlight")

    return body


__all__ = ["WEIGHTS", "build_query", "build_filters", "OBJECT_TYPES"]

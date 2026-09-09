from __future__ import annotations

from typing import Any, Mapping

from .fields import SOURCE_BY_TYPE, WEIGHTS

# 子句原语
def _term(field: str, value: Any) -> dict[str, Any]:
    return {"term": {field: str(value)}}  # keyword 存字符串，数字值转 str 保证命中


def _terms(field: str, values: Any) -> dict[str, Any]:
    vals = [str(v) for v in values] if isinstance(values, (list, tuple)) else [str(values)]
    return {"terms": {field: vals}}


def _nested(path: str, inner: Mapping[str, Any]) -> dict[str, Any]:
    # inner_hits 返回命中的那个数组元素（含 _source）
    return {"nested": {"path": path, "query": dict(inner), "inner_hits": {"_source": True}}}


def build_filters(type_: str, p: Mapping[str, Any]) -> list[dict[str, Any]]:
    """按类型组装 bool.filter。type_ 必须是具体类型（type=all 由 service 对每索引分别调用）。"""
    f: list[dict[str, Any]] = []

    project_id = p.get("project_id")
    if project_id is not None:
        f.append(_term("project_id", project_id))
    if p.get("status"):
        f.append(_term("identity.status", p["status"]))
    if p.get("presentation_type"):
        f.append(_term("presentation.type", p["presentation_type"]))

    if type_ == "evidence":
        if p.get("period"):
            f.append(_term("presentation.period.keyword", p["period"]))  # 原字段 text+standard，必须 .keyword
        if p.get("region"):
            f.append(_term("presentation.region", p["region"]))
        if p.get("industry"):
            f.append(_term("presentation.industry", p["industry"]))
        if p.get("source_type"):
            f.append(_terms("presentation.source_type", p["source_type"]))

    if type_ == "source" and p.get("confidence_level"):
        f.append(_term("experience.confidence_level", p["confidence_level"]))

    if type_ == "viewpoint":
        if p.get("claim_type"):
            f.append(_term("experience.claim_type", p["claim_type"]))
        if p.get("applicable_scenario"):
            f.append(_term("experience.applicable_scenario", p["applicable_scenario"]))
        if p.get("cross_validation_mode"):
            f.append(_term("experience.cross_validation_mode", p["cross_validation_mode"]))

    # source_ids 歧义：evidence 扁平 / viewpoint 嵌套
    if p.get("source_ids"):
        if type_ == "evidence":
            f.append(_terms("reasoning.source_ids", p["source_ids"]))
        elif type_ == "viewpoint":
            f.append(_nested("reasoning.steps", _terms("reasoning.steps.source_ids", p["source_ids"])))

    if p.get("evidence_ids") and type_ == "viewpoint":
        f.append(_nested("reasoning.steps", _terms("reasoning.steps.evidence_ids", p["evidence_ids"])))

    if p.get("responsible_role"):
        f.append(_nested("responsibility", _term("responsibility.operator.role", p["responsible_role"])))

    return f


def _multi_match(q: str, type_: str) -> dict[str, Any]:
    return {
        "multi_match": {
            "query": q,
            "type": "best_fields",
            "analyzer": "ik_smart",
            "fields": WEIGHTS[type_],
        }
    }


def build_query(type_: str, p: Mapping[str, Any]) -> dict[str, Any]:
    """返回可直接 `es.search(index=.., **build_query(...))` 的 kwargs。"""
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

    highlight = {
        "pre_tags": ["<em>"],
        "post_tags": ["</em>"],
        "fields": {f.split("^", 1)[0]: {} for f in WEIGHTS[type_]},
    }

    page = max(int(p.get("page", 1)), 1)
    size = max(int(p.get("size", 20)), 1)

    body: dict[str, Any] = {
        "query": query,
        "highlight": highlight,
        "source": SOURCE_BY_TYPE[type_],
        "from_": (page - 1) * size,
        "size": size,
        "track_total_hits": True,
    }

    if p.get("highlight", True) is False:
        body.pop("highlight")

    return body


__all__ = ["build_query", "build_filters"]

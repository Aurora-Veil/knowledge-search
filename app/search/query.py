from __future__ import annotations

from typing import Any, Mapping, Sequence

from .fields import *

MATCH_MODES = ("or","and","phrase")


class WindowTooDeep(ValueError):
    """
    The requested page is past RESULT_WINDOW.
    """


def _term(field: str, value: Any) -> dict[str, Any]:
    return {"term": {field: str(value)}}

def _terms(field: str, values: Any) -> dict[str, Any]:
    vals = [str(v) for v in values] if isinstance(values, (list, tuple)) else [str(values)]
    return {"terms": {field: vals}}


def _nested(path: str, inner: Mapping[str, Any], inner_hits: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {"path": path, "query": dict(inner)}
    if inner_hits:
        body["inner_hits"] = {"_source": True}
    return {"nested": body}


def _page_size(p: Mapping[str, Any]) -> tuple[int, int]:
    return max(int(p.get("page", 1)), 1), max(int(p.get("size", 20)), 1)


def window(p: Mapping[str, Any]) -> int:
    """
    How many hits every retriever is asked for, or raise if the page is too deep.

    """
    page, size = _page_size(p)
    if page * size > RESULT_WINDOW:
        raise WindowTooDeep(
            f"page*size = {page * size} exceeds RESULT_WINDOW = {RESULT_WINDOW}; "
            f"fusion re-reads that many hits from every retriever to stay page-stable"
        )
    return RESULT_WINDOW


def build_filters(type_: str, p: Mapping[str, Any], inner_hits: bool = True) -> list[dict[str, Any]]:
    """
    build bool.filter by type. 
    type_ must be one of WEIGHTS keys.
    p is a dict of filter parameters.

    Only filters that FIELD_TYPES declares applicable to ``type_`` are emitted;

    inner_hits is off for the kNN branch
    """
    f: list[dict[str, Any]] = []

    pid = p.get("project_id")
    if pid not in (None, []):
        f.append(_terms("project_id", pid))
    if p.get("status"):
        f.append(_term("identity.status", p["status"]))
    if p.get("presentation_type"):
        f.append(_term("presentation.type", p["presentation_type"]))
    if p.get("publisher") and type_ in PUBLISHER_FIELD:
        f.append(_terms(PUBLISHER_FIELD[type_], p["publisher"]))

    if type_ == "evidence":
        if p.get("period"):
            f.append(_term("presentation.period.keyword", p["period"]))
        if p.get("region"):
            f.append(_term("presentation.region", p["region"]))
        if p.get("industry"):
            f.append(_term("presentation.industry", p["industry"]))
        if p.get("source_type"):
            f.append(_terms("presentation.source_type", p["source_type"]))

    if p.get("confidence_level") and type_ in CONFIDENCE_LEVEL_TYPES:
        f.append(_term("experience.confidence_level", p["confidence_level"]))

    if type_ == "viewpoint":
        if p.get("claim_type"):
            f.append(_term("experience.claim_type", p["claim_type"]))
        if p.get("applicable_scenario"):
            f.append(_term("experience.applicable_scenario", p["applicable_scenario"]))
        if p.get("cross_validation_mode"):
            f.append(_term("experience.cross_validation_mode", p["cross_validation_mode"]))

    # source_ids 
    if p.get("source_ids") and type_ == "evidence":
        f.append(_terms("reasoning.source_ids", p["source_ids"]))

    # viewpoint source_ids / evidence_ids in reasoning.steps：
    if type_ == "viewpoint":
        steps_inner = []
        if p.get("source_ids"):
            steps_inner.append(_terms("reasoning.steps.source_ids", p["source_ids"]))
        if p.get("evidence_ids"):
            steps_inner.append(_terms("reasoning.steps.evidence_ids", p["evidence_ids"]))
        if steps_inner:
            f.append(_nested("reasoning.steps", {"bool": {"filter": steps_inner}}, inner_hits))

    if p.get("responsible_role"):
        f.append(_nested("responsibility", _term("responsibility.operator.role", p["responsible_role"]),
                         inner_hits))

    _check_applicability_drift(type_, p)
    return f


def _check_applicability_drift(type_: str, p: Mapping[str, Any]) -> None:
    """
    Guard: a filter passed in ``p`` must be declared applicable to ``type_`` in FIELD_TYPES, 
    otherwise the per-type branches above and the FIELD_TYPES table have drifted apart.
    """
    for key, allowed in FIELD_TYPES.items():
        if p.get(key) and type_ not in allowed:
            raise ValueError(
                f"filter {key!r} is not applicable to type {type_!r} "
                f"(FIELD_TYPES says {allowed}); build_filters and FIELD_TYPES have drifted"
            )


def _multi_match(q: str, type_: str, mode: str = "or") -> dict[str, Any]:
    mm: dict[str, Any] = {
        "query": q,
        "analyzer": "ik_smart",
        "fields": WEIGHTS[type_],
        "type": "best_fields",
    }
    if mode == "and":
        mm["operator"] = "and"
    elif mode == "phrase":
        mm["type"] = "phrase"
    return {"multi_match": mm}

def build_query(type_: str, p: Mapping[str, Any]) -> dict[str, Any]:
    """ return a dict for Elasticsearch query body."""
    if type_ not in WEIGHTS:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(WEIGHTS)})")

    mode = p.get("mode") or "or"
    if mode not in MATCH_MODES:
        raise ValueError(f"unknown mode: {mode!r} (expected one of {MATCH_MODES})")

    must: list[dict[str, Any]] = []
    q = p.get("q")
    if q:
        must.append(_multi_match(q, type_, mode))

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

    page, size = _page_size(p)
    window(p)   # depth guard, shared with the kNN branch

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


def build_knn_query(type_: str, p: Mapping[str, Any], vector: Sequence[float]) -> dict[str, Any]:
    """
    kNN-only body: the vector branch, with no lexical clause and no highlight.
    """
    if type_ not in WEIGHTS:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(WEIGHTS)})")

    need = window(p)
    knn: dict[str, Any] = {
        "field": EMBED_FIELD,
        "query_vector": list(vector),
        "k": need,
        "num_candidates": max(need * KNN_NUM_CANDIDATES_FACTOR, need + 10),
    }

    filters = build_filters(type_, p, inner_hits=False)
    if filters:
        knn["filter"] = filters

    return {"knn": knn, "source": SOURCE_BY_TYPE[type_], "size": need}


__all__ = ["build_query", "build_knn_query", "build_filters", "window", "MATCH_MODES"]

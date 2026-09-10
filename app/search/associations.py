"""
Asscciations API

DAG: viewpoint → evidence → source no-cycle
"""

from typing import Any, Mapping

from ..config import INDEX_BY_TYPE, OBJECT_TYPES
from ..db import get_es
from .fields import SOURCE_BY_TYPE
from .response import hit_to_card

DIRECTIONS: tuple[str, ...] = ("out", "in", "both")
INCLUDES: tuple[str, ...] = ("card", "ref")

MAX_HOPS = 2
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

REL_STEP_EVIDENCE = "step_evidence"
REL_STEP_SOURCE = "step_source"
REL_EVIDENCE_SOURCE = "evidence_source"

_EXPAND_SOURCE = ["id", "project_id", "oirf_id", "identity.name", "identity.status", "reasoning"]

_SCAN_SIZE = 1000


def _out_edges(doc: Mapping[str, Any] | None, object_type: str) -> list[tuple[str, str, str, int | None, str | None]]:
    """
    doc out degree: references to other objects.
    """
    if not doc:
        return []
    reasoning = doc.get("reasoning") or {}

    if object_type == "viewpoint":
        out: list[tuple[str, str, str, int | None, str | None]] = []
        for i, step in enumerate(reasoning.get("steps") or []):
            label = step.get("to")
            for x in step.get("evidence_ids") or []:
                out.append((str(x), "evidence", REL_STEP_EVIDENCE, i, label))
            for x in step.get("source_ids") or []:
                out.append((str(x), "source", REL_STEP_SOURCE, i, label))
        return out

    if object_type == "evidence":
        return [(str(x), "source", REL_EVIDENCE_SOURCE, None, None)
                for x in reasoning.get("source_ids") or []]

    return []


def _scan(es: Any, project_id: int, object_type: str, inner: dict[str, Any],
          source: list[str]) -> list[dict[str, Any]]:
    """ project limited _source scan """
    body = {
        "query": {"bool": {"filter": [{"term": {"project_id": str(project_id)}}, inner]}},
        "_source": source,
        "size": _SCAN_SIZE,
    }
    return es.search(index=INDEX_BY_TYPE[object_type], **body)["hits"]["hits"]


def _fetch(es: Any, project_id: int, ids_by_type: Mapping[str, str],
           source: list[str]) -> dict[str, dict[str, Any]]:
    """ featch _source in (oirf_id, project_id)"""
    groups: dict[str, list[str]] = {}
    for oid, type_ in ids_by_type.items():
        groups.setdefault(type_, []).append(oid)

    docs: dict[str, dict[str, Any]] = {}
    for type_, ids in groups.items():
        body = {
            "query": {"bool": {"filter": [
                {"term": {"project_id": str(project_id)}},
                {"terms": {"oirf_id": sorted(ids)}},
            ]}},
            "_source": source,
            "size": max(len(ids), 1),
        }
        for hit in es.search(index=INDEX_BY_TYPE[type_], **body)["hits"]["hits"]:
            src = hit.get("_source") or {}
            if src.get("oirf_id"):
                docs[src["oirf_id"]] = src
    return docs


def _reverse_edges(es: Any, project_id: int, frontier: Mapping[str, str]
                   ) -> list[tuple[str, str, str, str, int | None, str | None]]:
    """
    frontier in-degree edges: (from, from_type, to, rel, step, label)
    """
    ev_targets = [i for i, t in frontier.items() if t == "evidence"]
    src_targets = [i for i, t in frontier.items() if t == "source"]
    targets = set(ev_targets) | set(src_targets)
    if not targets:
        return []

    found: dict[tuple[str, str], dict[str, Any]] = {}
    if ev_targets:
        inner = {"nested": {"path": "reasoning.steps",
                            "query": {"terms": {"reasoning.steps.evidence_ids": ev_targets}}}}
        for hit in _scan(es, project_id, "viewpoint", inner, _EXPAND_SOURCE):
            src = hit.get("_source") or {}
            if src.get("oirf_id"):
                found[("viewpoint", src["oirf_id"])] = src
    if src_targets:
        inner = {"terms": {"reasoning.source_ids": src_targets}}
        for hit in _scan(es, project_id, "evidence", inner, _EXPAND_SOURCE):
            src = hit.get("_source") or {}
            if src.get("oirf_id"):
                found[("evidence", src["oirf_id"])] = src
        inner = {"nested": {"path": "reasoning.steps",
                            "query": {"terms": {"reasoning.steps.source_ids": src_targets}}}}
        for hit in _scan(es, project_id, "viewpoint", inner, _EXPAND_SOURCE):
            src = hit.get("_source") or {}
            if src.get("oirf_id"):
                found[("viewpoint", src["oirf_id"])] = src

    edges: list[tuple[str, str, str, str, int | None, str | None]] = []
    for (from_type, from_id), doc in found.items():
        for (to, _to_type, rel, step, label) in _out_edges(doc, from_type):
            if to in targets:
                edges.append((from_id, from_type, to, rel, step, label))
    return edges


def _traverse(es: Any, project_id: int, root_id: str, root_type: str, hops: int, direction: str
              ) -> tuple[dict[str, str], dict[str, str], dict[tuple, dict[str, Any]]]:
    """
    return (nodes, dir_of, edges)
    nodes: oirf_id → object_type
    dir_of: oirf_id → direction (out/in)
    edges: (from, to, rel, step) → {from, to, rel, step, hop, label}
    """
    nodes: dict[str, str] = {root_id: root_type}
    dir_of: dict[str, str] = {}
    edges: dict[tuple, dict[str, Any]] = {}
    frontier: dict[str, str] = {root_id: root_type}

    for hop in range(1, hops + 1):
        new: dict[str, str] = {}

        def add_edge(new_id: str, new_type: str, frm: str, to: str, rel: str,
                     step: int | None, label: str | None, arrived: str) -> None:
            edges.setdefault((frm, to, rel, step),
                             {"from": frm, "to": to, "rel": rel, "step": step,
                              "hop": hop, "label": label})
            if new_id not in nodes and new_id not in new:
                new[new_id] = new_type
                dir_of[new_id] = arrived

        if direction in ("out", "both"):
            docs = _fetch(es, project_id, frontier, _EXPAND_SOURCE)
            for fid in sorted(frontier):
                for (to, to_type, rel, step, label) in _out_edges(docs.get(fid), frontier[fid]):
                    add_edge(to, to_type, fid, to, rel, step, label, "out")

        if direction in ("in", "both"):
            for (frm, frm_type, to, rel, step, label) in _reverse_edges(es, project_id, frontier):
                add_edge(frm, frm_type, frm, to, rel, step, label, "in")

        nodes.update(new)
        frontier = new
        if not new:
            break

    return nodes, dir_of, edges


def _select(nodes: Mapping[str, str], root_id: str, dir_of: Mapping[str, str],
            types: set[str] | None, limit: int) -> tuple[list[str], list[str]]:
    """
    buckets in (direction, type) → list[oirf_id]
    """
    buckets: dict[tuple[str, str], list[str]] = {}
    for oid, type_ in nodes.items():
        if oid == root_id:
            continue
        if types is not None and type_ not in types:
            continue
        buckets.setdefault((dir_of.get(oid, "out"), type_), []).append(oid)

    kept: list[str] = []
    truncated: list[str] = []
    for key in sorted(buckets):
        ids = sorted(buckets[key])
        if len(ids) > limit:
            truncated.append("%s:%s" % key)
        kept.extend(ids[:limit])
    return kept, truncated


def _shape(doc: Mapping[str, Any], object_type: str, include: str) -> dict[str, Any]:
    if include == "ref":
        identity = doc.get("identity") or {}
        return {
            "id": doc.get("id"),
            "oirf_id": doc.get("oirf_id"),
            "object_type": object_type,
            "project_id": doc.get("project_id"),
            "identity": {"name": identity.get("name"), "status": identity.get("status")},
        }
    card = hit_to_card({"_source": dict(doc)}, object_type)
    card.pop("score", None)
    card.pop("raw_score", None)
    return card


def neighborhood(object_type: str, oirf_id: str, project_id: int, hops: int = 1,
                 direction: str = "both", types: set[str] | None = None,
                 include: str = "card", limit: int = DEFAULT_LIMIT) -> dict[str, Any] | None:
    """`GET /api/v1/associations/... """
    if object_type not in OBJECT_TYPES:
        raise ValueError(f"unknown object_type: {object_type!r} (expected one of {list(OBJECT_TYPES)})")
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r} (expected one of {list(DIRECTIONS)})")
    if include not in INCLUDES:
        raise ValueError(f"unknown include: {include!r} (expected one of {list(INCLUDES)})")
    if not 1 <= hops <= MAX_HOPS:
        raise ValueError(f"hops out of range: {hops!r} (expected 1..{MAX_HOPS})")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit out of range: {limit!r} (expected 1..{MAX_LIMIT})")

    es = get_es()
    root_doc = _fetch(es, project_id, {oirf_id: object_type}, SOURCE_BY_TYPE[object_type]).get(oirf_id)
    if root_doc is None:
        return None

    nodes, dir_of, edges = _traverse(es, project_id, oirf_id, object_type, hops, direction)
    kept, truncated = _select(nodes, oirf_id, dir_of, types, limit)

    docs: dict[str, dict[str, Any]] = {}
    by_type: dict[str, dict[str, str]] = {}
    for oid in kept:
        by_type.setdefault(nodes[oid], {})[oid] = nodes[oid]
    for type_, ids in by_type.items():
        source = _EXPAND_SOURCE if include == "ref" else SOURCE_BY_TYPE[type_]
        docs.update(_fetch(es, project_id, ids, source))

    missing = sorted(oid for oid in kept if oid not in docs)

    present = {oirf_id} | set(docs)
    out_edges = [e for e in edges.values() if e["from"] in present and e["to"] in present]
    out_edges.sort(key=lambda e: (e["hop"], e["from"], e["to"], e["rel"],
                                  -1 if e["step"] is None else e["step"]))

    return {
        "root": _shape(root_doc, object_type, include),
        "project_id": project_id,
        "hops": hops,
        "direction": direction,
        "include": include,
        "nodes": [_shape(docs[oid], nodes[oid], include) for oid in sorted(docs, key=lambda i: (nodes[i], i))],
        "edges": out_edges,
        "truncated": truncated,
        "missing": missing,
    }


__all__ = ["neighborhood", "DIRECTIONS", "INCLUDES", "MAX_HOPS", "MAX_LIMIT", "DEFAULT_LIMIT",
           "REL_STEP_EVIDENCE", "REL_STEP_SOURCE", "REL_EVIDENCE_SOURCE"]

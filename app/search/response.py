from __future__ import annotations

from typing import Any

_CARD_FIELDS = ("identity", "presentation", "reasoning", "experience", "responsibility")


def hit_to_card(hit: dict[str, Any], object_type: str) -> dict[str, Any]:
    """ES hit → card dict for API response"""
    src = hit.get("_source") or {}

    card: dict[str, Any] = {
        "id": src.get("id") or hit.get("_id"),
        "object_type": object_type,
        "project_id": src.get("project_id"),
        "oirf_id": src.get("oirf_id"),
        "score": hit.get("_score"),
        "raw_score": hit.get("_score"),
    }

    for f in _CARD_FIELDS:
        if f in src and src[f] is not None:
            card[f] = src[f]

    if "highlight" in hit:
        card["highlight"] = hit["highlight"]
    if "inner_hits" in hit:
        card["inner_hits"] = hit["inner_hits"]
        
    return card


def hit_to_card_report(hit: dict[str, Any]) -> dict[str, Any]:
    src = hit.get("_source") or {}
    
    return {
        "report_id": src.get("report_id") or hit.get("_id"),
        "title": src.get("title"),
        "summary": src.get("summary"),
        "industry": src.get("industry") or [],
        "layout": src.get("layout"),
        "publish_date": src.get("publish_date"),
        "url": src.get("url"),
    }

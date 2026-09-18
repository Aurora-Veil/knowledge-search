from __future__ import annotations

from datetime import date
from typing import Any, Mapping

PARAM = "time_weight"

SCALE_DAYS = 365.0     # 半衰期
OFFSET_DAYS = 90.0     # 免罚区
HALF = 0.5             # scale 处的取值


def weight(p: Mapping[str, Any]) -> float:
    raw = p.get(PARAM)
    return 0.0 if raw is None else min(max(float(raw), 0.0), 1.0)


def origin() -> str:
    return date.today().isoformat()


def rescore(field: str, w: float, window: int) -> dict[str, Any]:
    source = (
        "_score * (1.0 - params.w + params.w * decayDateExp("
        f"params.origin, params.scale, params.offset, params.decay, doc['{field}'].value))"
    )
    return {
        "window_size": window,
        "script": {"script": {
            "source": source,
            "params": {
                "w": w,
                "origin": origin(),
                "scale": f"{int(SCALE_DAYS)}d",
                "offset": f"{int(OFFSET_DAYS)}d",
                "decay": HALF,
            },
        }},
    }


__all__ = ["PARAM", "SCALE_DAYS", "OFFSET_DAYS", "HALF",
           "weight", "origin", "rescore"]

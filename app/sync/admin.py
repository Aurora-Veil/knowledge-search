"""索引生命周期：存在判断 / 按 mapping/*.json 建索引 / drop / recreate / mapping 差异提示。

约定：默认路径绝不 drop 已有索引；drop 只发生在显式 `--recreate`。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..db import resolve_es

MAPPING_DIR = Path(__file__).resolve().parents[2] / "mapping"

MAPPING_FILE: dict[str, str] = {
    "source": "source_mapping.json",
    "evidence": "evidence_mapping.json",
    "viewpoint": "viewpoint_mapping.json",
}


def load_mapping(type_: str) -> dict[str, Any]:
    """读 mapping/*.json（含 settings 与 mappings 两段）。"""
    if type_ not in MAPPING_FILE:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(MAPPING_FILE)})")
    with (MAPPING_DIR / MAPPING_FILE[type_]).open(encoding="utf-8") as f:
        return json.load(f)


def exists(index: str, es=None) -> bool:
    return bool(resolve_es(es).indices.exists(index=index))


def create(index: str, type_: str, es=None) -> None:
    """按 mapping 文件建索引（调用方负责确认它尚不存在）。"""
    body = load_mapping(type_)
    resolve_es(es).indices.create(
        index=index, settings=body.get("settings"), mappings=body.get("mappings")
    )


def drop(index: str, es=None) -> None:
    """删索引；不存在视为已达成（幂等）。只应由显式 `--recreate` 路径调用。"""
    client = resolve_es(es)
    if exists(index, client):
        client.indices.delete(index=index)


def recreate(index: str, type_: str, es=None) -> None:
    """drop（若存在）→ 按 mapping 文件 create。默认路径不调用它。"""
    client = resolve_es(es)
    drop(index, client)
    create(index, type_, client)


def current_mapping(index: str, es=None) -> dict[str, Any]:
    """ES 里该索引当前的 mappings 段。"""
    res = resolve_es(es).indices.get_mapping(index=index)
    return res[index]["mappings"]


def _flatten(node: Any, prefix: str = "") -> dict[str, str]:
    """把嵌套 mappings 拍平成 {字段路径: 描述}，便于逐条比差异。

    需要归一化，否则"文件原文"与"ES 规整后的 get_mapping"会被比出假差异：
      · `type: object` + properties 的容器字段本身不入表（ES 不回显该冗余 type），只摊开子字段
      · `search_analyzer == analyzer` 时省略（ES 的默认行为，不回显）
      · 布尔标量统一小写（`false` 与 `"false"` 等价）
    """
    if not isinstance(node, dict):
        return {prefix: str(node).lower() if isinstance(node, bool) else str(node)}

    node_type = node.get("type")
    children = [(n, v) for k in ("properties", "fields") for n, v in (node.get(k) or {}).items()]

    out: dict[str, str] = {}
    if node_type and not (node_type == "object" and children):
        analyzer = node.get("analyzer")
        extras = [
            f"{k}={node[k]}" for k in ("analyzer", "search_analyzer")
            if k in node and not (k == "search_analyzer" and node[k] == analyzer)
        ]
        out[prefix] = node_type + (f" [{', '.join(extras)}]" if extras else "")

    if children:
        for name, sub in children:
            out.update(_flatten(sub, f"{prefix}.{name}" if prefix else name))
        return out
    if node_type:
        return out

    for name, sub in node.items():  # 纯容器（无 type、无 properties/fields）
        out.update(_flatten(sub, f"{prefix}.{name}" if prefix else name))
    return out


def diff_mapping(current: dict[str, Any], wanted: dict[str, Any]) -> list[str]:
    """逐字段比差异，返回人可读行（空列表 = 完全一致）。"""
    cur, want = _flatten(current), _flatten(wanted)
    lines: list[str] = []
    for path in sorted(set(cur) | set(want)):
        if path not in cur:
            lines.append(f"+ {path}: {want[path]}")
        elif path not in want:
            lines.append(f"- {path}: {cur[path]}")
        elif cur[path] != want[path]:
            lines.append(f"~ {path}: {cur[path]} -> {want[path]}")
    return lines


def inspect_index(index: str, type_: str, es=None) -> tuple[bool, list[str]]:
    """重建前的计划信息：(索引是否已存在, 现有 mapping 与文件片段的差异行)。"""
    if not exists(index, es):
        return False, []
    file_mappings = load_mapping(type_).get("mappings") or {}
    return True, diff_mapping(current_mapping(index, es), file_mappings)


__all__ = [
    "MAPPING_DIR", "MAPPING_FILE", "load_mapping", "exists", "create", "drop",
    "recreate", "current_mapping", "diff_mapping", "inspect_index",
]

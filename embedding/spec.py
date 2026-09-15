"""The vector text spec: read ``embedding/fields.json``, resolve, join, hash.

Path grammar
------------

The spec file holds paths as pure data; the semantics live here.

    a.b          a scalar leaf
    a.b[].c      ``[]`` marks an array; the remaining path applies to every element
    a.b          if the value is itself an array of scalars, all elements are taken
                 (same rule as above, only without the marker)

Resolution flattens the whole document first, rewriting array indices as
``[]``, then matches each spec path by exact path or by the ``path + "[]"``
prefix. Matching on a bare ``startswith(path)`` would be wrong: it makes
``presentation.content`` swallow ``presentation.contents`` as well.

Order
-----

Output order follows the spec, never the document's key order. The text feeds
:func:`text_hash`, so a re-serialized document with keys in a different order
must not look like a different document.

Leaves
------

Every string leaf is stripped, ``None`` is dropped, and any other scalar is
stringified. The spec's separator is therefore the only whitespace the builder
itself introduces -- which is what makes the hash reproducible.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

SPEC_PATH = Path(__file__).with_name("fields.json")

with SPEC_PATH.open(encoding="utf-8") as _f:
    SPEC: dict[str, Any] = json.load(_f)

MODEL: dict[str, Any] = SPEC["model"]
TYPES: dict[str, list[str]] = SPEC["types"]
SEPARATOR: str = SPEC["text"]["separator"]
SKIP_EMPTY: bool = bool(SPEC["text"]["skip_empty"])


def flatten(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield (path, leaf) for every leaf; array indices become []."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from flatten(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for item in node:
            yield from flatten(item, path + "[]")
    else:
        yield path, node


def _leaf_text(value: Any) -> str | None:
    if value is None:
        return None
    return (value if isinstance(value, str) else str(value)).strip()


def build_text(doc: Mapping[str, Any], type_: str, sep: str | None = None) -> str:
    """Concatenate the spec's fields of one entity into a single passage."""
    paths = TYPES.get(type_)
    if paths is None:
        raise ValueError(f"unknown type: {type_!r} (expected one of {list(TYPES)})")

    leaves = list(flatten(doc))
    parts: list[str] = []
    for path in paths:
        prefix = path if path.endswith("[]") else path + "[]"
        for leaf_path, value in leaves:
            if leaf_path != path and not leaf_path.startswith(prefix):
                continue
            text = _leaf_text(value)
            if text is None or (SKIP_EMPTY and not text):
                continue
            parts.append(text)
    return (SEPARATOR if sep is None else sep).join(parts)


def text_hash(text: str) -> str:
    """sha256 of the passage.

    Covers the text only. The hash is used to detect changes in the text.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["SPEC", "MODEL", "TYPES", "SEPARATOR", "SKIP_EMPTY",
           "flatten", "build_text", "text_hash"]

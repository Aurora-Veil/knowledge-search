"""
bge passage / query encoder.

"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Sequence

from .spec import MODEL

# Read by huggingface_hub / transformers at import time
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")


def _cache_root() -> Path:
    path = Path(MODEL["cache_dir"])
    return path if path.is_absolute() else _REPO_ROOT / path


def _is_complete(snapshot: Path) -> bool:
    return (snapshot / "config.json").is_file() and any(
        (snapshot / name).is_file() for name in _WEIGHT_FILES
    )


def resolve_snapshot() -> Path:
    """
    Pick a usable snapshot out of the local hub cache.

    """
    model_dir = _cache_root() / "hub" / ("models--" + MODEL["name"].replace("/", "--"))
    snapshots = model_dir / "snapshots"
    if not snapshots.is_dir():
        raise FileNotFoundError(
            f"no local snapshot of {MODEL['name']} under {snapshots}; "
            f"check model.cache_dir in embedding/fields.json"
        )

    ref = model_dir / "refs" / "main"
    if ref.is_file():
        candidate = snapshots / ref.read_text(encoding="utf-8").strip()
        if _is_complete(candidate):
            return candidate

    for candidate in sorted(p for p in snapshots.iterdir() if p.is_dir()):
        if _is_complete(candidate):
            return candidate

    raise FileNotFoundError(f"no complete snapshot of {MODEL['name']} under {snapshots}")


class Encoder:
    """Thin wrapper over the sentence-transformers model."""

    def __init__(self, batch_size: int = 32, device: str | None = None) -> None:
        self.batch_size = batch_size
        self.device = device
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def dim(self) -> int:
        return int(MODEL["dims"])

    def _load(self) -> Any:
        # Locked across the whole load, not just the swap: a second caller that
        # slipped past the check would otherwise load its own copy of the
        # weights. Encoding itself runs outside the lock.
        with self._lock:
            if self._model is None:
                import torch
                from sentence_transformers import SentenceTransformer

                if self.device is None:
                    self.device = "cuda" if torch.cuda.is_available() else "cpu"
                model = SentenceTransformer(str(resolve_snapshot()), device=self.device)
                model.max_seq_length = int(MODEL["max_tokens"])
                self._model = model
            return self._model

    def encode_passages(self, texts: Sequence[str],
                        show_progress_bar: bool = False) -> list[list[float]]:
        """Encode passages. """
        return self._encode(texts, prefix="", show_progress_bar=show_progress_bar)

    def encode_query(self, query: str, show_progress_bar: bool = False) -> list[float]:
        """Encode one search query."""
        prefix = MODEL.get("query_instruction") or ""
        return self._encode([query], prefix=prefix,
                            show_progress_bar=show_progress_bar)[0]

    def _encode(self, texts: Sequence[str], prefix: str,
                show_progress_bar: bool) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(
            [prefix + text for text in texts],
            batch_size=self.batch_size,
            normalize_embeddings=bool(MODEL["normalize_embeddings"]),
            convert_to_numpy=True,
            show_progress_bar=show_progress_bar,
        )
        # tolist() is the boundary that keeps float32 out of the index: numpy
        # scalars are not JSON serializable and ES rejects the whole bulk item.
        out = [vector.tolist() for vector in vectors]
        for vector in out:
            if len(vector) != self.dim:
                raise ValueError(f"model returned {len(vector)} dims, spec says {self.dim}")
        return out


__all__ = ["Encoder", "resolve_snapshot"]

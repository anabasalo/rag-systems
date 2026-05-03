"""Embedder protocol and a sentence-transformers implementation.

Tests inject a deterministic fake; the real embedder is loaded lazily so
importing this module does not trigger a model download.

See ADR 0003 for why `all-MiniLM-L6-v2` is the default model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Embedder(Protocol):
    """Anything that can turn texts into dense vectors."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    """Wraps `sentence_transformers.SentenceTransformer`.

    The model is loaded on first `embed()` call to keep `import` cheap.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            # Imported lazily so `from app.core.embedders import ...` does
            # not pull torch/sentence-transformers unless we actually embed.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(list(texts), convert_to_numpy=True, show_progress_bar=False)
        return [vec.tolist() for vec in vectors]

    @property
    def model_name(self) -> str:
        return self._model_name

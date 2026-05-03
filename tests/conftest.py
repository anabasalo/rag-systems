"""Shared pytest fixtures.

Tests use a deterministic fake embedder and a per-test ChromaDB directory
so the suite is fast and runs offline. The real sentence-transformers
model is never loaded under pytest.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import pytest


@pytest.fixture
def tmp_chroma_dir(tmp_path: Path) -> Path:
    """A clean ChromaDB persistence directory per test."""
    persist = tmp_path / "chroma"
    persist.mkdir()
    return persist


class _DeterministicEmbedder:
    """A reproducible fake embedder.

    Returns a `dimension`-length vector derived from a hash of (text, index).
    Two distinct strings produce different vectors; the same string always
    produces the same vector.
    """

    def __init__(self, dimension: int = 32) -> None:
        self._dim = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        out: list[float] = []
        for i in range(self._dim):
            digest = hashlib.sha256(f"{text}::{i}".encode()).digest()
            value = int.from_bytes(digest[:4], "big")
            # Map roughly to [-1, 1].
            out.append((value / (2**31)) - 1.0)
        return out

    @property
    def dimension(self) -> int:
        return self._dim


@pytest.fixture
def fake_embedder() -> _DeterministicEmbedder:
    return _DeterministicEmbedder()


@pytest.fixture
def make_doc(tmp_path: Path):
    """Factory: create a temp file with the given name and content."""

    def _make(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    return _make

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


class _FakeGenerator:
    """Replaces ``GroqGenerator`` in API tests.

    Records the last ``(system, user)`` pair so a test can assert the prompt
    is shaped correctly. Returns a deterministic ``GenerationResult``.
    """

    def __init__(
        self,
        answer: str = "Mock answer.",
        prompt_tokens: int | None = 100,
        completion_tokens: int | None = 20,
    ) -> None:
        self.answer = answer
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.last_call: tuple[str, str] | None = None
        self.calls = 0

    def generate(self, system: str, user: str):
        from app.core.generation import GenerationResult

        self.calls += 1
        self.last_call = (system, user)
        return GenerationResult(
            answer=self.answer,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )


@pytest.fixture
def fake_generator() -> _FakeGenerator:
    return _FakeGenerator()


class _FakeScorer:
    """Deterministic stand-in for ``RagasScorer`` — no LLM calls.

    Returns the same score (0.5 by default) for every metric of every
    item. Items without a ``ground_truth`` correctly receive ``None``
    for metrics that require one, mirroring the real scorer's contract.
    Records the inputs so tests can assert *what* the runner asked the
    scorer to score.
    """

    def __init__(self, value: float = 0.5) -> None:
        self.value = value
        self.calls: list = []

    def score(self, items):
        from app.eval.scorer import METRICS_REQUIRING_GROUND_TRUTH

        self.calls.append(list(items))
        out = []
        for item in items:
            row: dict[str, float | None] = {
                "faithfulness": self.value,
                "answer_relevancy": self.value,
            }
            if item.ground_truth is None:
                row["context_precision"] = None
                row["context_recall"] = None
            else:
                row["context_precision"] = self.value
                row["context_recall"] = self.value
            # Mark unused name to keep ruff happy on imported constant
            assert "context_recall" in METRICS_REQUIRING_GROUND_TRUTH
            out.append(row)
        return out


@pytest.fixture
def fake_scorer() -> _FakeScorer:
    return _FakeScorer()


@pytest.fixture
def tmp_query_log(tmp_path: Path):
    """A QueryLogger that writes to a tmp file instead of ./logs/."""
    from app.observability.query_log import QueryLogger

    return QueryLogger(path=tmp_path / "queries.jsonl")


@pytest.fixture
def client(tmp_chroma_dir, fake_embedder, fake_generator, fake_scorer, tmp_query_log):
    """A FastAPI TestClient with all external deps stubbed.

    - Vector store: real ChromaDB pointed at ``tmp_chroma_dir``
    - Embedder: deterministic fake (no model download)
    - Generator: ``_FakeGenerator`` (no Groq call)
    - Scorer:    ``_FakeScorer``    (no RAGAS call)
    - QueryLogger: writes to a tmp file (no ./logs/ pollution)
    """
    from fastapi.testclient import TestClient

    from app.api.deps import (
        get_embedder,
        get_generator,
        get_query_logger,
        get_scorer,
        get_settings_dep,
        get_vector_store,
    )
    from app.config import Settings
    from app.db.vector_store import VectorStore
    from app.main import create_app

    app = create_app()
    store = VectorStore(persist_dir=tmp_chroma_dir)

    # Drop the similarity floor for API tests. The deterministic fake embedder
    # returns essentially random-similarity vectors, so a non-zero floor would
    # filter all results and mask the behavior we are actually testing.
    test_settings = Settings(similarity_floor=-1.0)

    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    app.dependency_overrides[get_generator] = lambda: fake_generator
    app.dependency_overrides[get_scorer] = lambda: fake_scorer
    app.dependency_overrides[get_query_logger] = lambda: tmp_query_log
    app.dependency_overrides[get_settings_dep] = lambda: test_settings

    test_client = TestClient(app)
    # Attach helpers so individual tests can reach the fakes / app.
    test_client.fake_generator = fake_generator  # type: ignore[attr-defined]
    test_client.fake_scorer = fake_scorer  # type: ignore[attr-defined]
    test_client.query_log = tmp_query_log  # type: ignore[attr-defined]
    test_client.app_instance = app  # type: ignore[attr-defined]
    return test_client

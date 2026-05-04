"""Phase 3 integration tests for BM25 + improved_retrieve.

These run against a real (in-tmp_path) ChromaDB and the deterministic
fake embedder. They validate the *plumbing* — that BM25 sees the right
chunks, that doc_filter is honored, that improved_retrieve returns ``k``
chunks — rather than reasoning about LLM answer quality (that is
Phase 4's job).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import CollectionNotFound
from app.core.ingestion import ingest
from app.core.retrieval import (
    bm25_retrieve,
    improved_retrieve,
)
from app.db.vector_store import VectorStore


@pytest.fixture
def populated_store(tmp_chroma_dir, fake_embedder, make_doc):
    """A vector store with three docs in collection ``alpha``."""
    store = VectorStore(persist_dir=tmp_chroma_dir)

    # Three short docs so each fits in one chunk under default chunk_size.
    docs: list[Path] = [
        make_doc("hpa.md", "The Horizontal Pod Autoscaler scales pods based on CPU."),
        make_doc(
            "vpa.md", "The Vertical Pod Autoscaler adjusts container memory and CPU requests."
        ),
        make_doc("ca.md", "The Cluster Autoscaler resizes the node pool when pods are pending."),
    ]
    for path in docs:
        ingest(
            file_path=path,
            collection="alpha",
            tags=["scaling"],
            embedder=fake_embedder,
            vector_store=store,
            chunk_size=2000,
            chunk_overlap=200,
        )
    return store


# --- bm25_retrieve -----------------------------------------------------------


def test_bm25_finds_keyword_match_even_with_random_embeddings(populated_store, fake_embedder):
    """The fake embedder is deterministic-but-arbitrary, so vector search
    cannot reliably retrieve the HPA doc for an HPA query. BM25 can,
    because it scores on actual word overlap."""
    result = bm25_retrieve(
        question="horizontal pod autoscaler",
        collection="alpha",
        vector_store=populated_store,
        k=1,
    )
    assert result.strategy == "bm25"
    assert len(result.chunks) == 1
    assert result.chunks[0].doc_name == "hpa.md"


def test_bm25_returns_at_most_k(populated_store):
    result = bm25_retrieve(
        question="autoscaler",
        collection="alpha",
        vector_store=populated_store,
        k=2,
    )
    assert len(result.chunks) == 2


def test_bm25_respects_doc_filter(populated_store):
    """``doc_filter.doc_name`` must restrict the BM25 corpus, not just
    post-filter the result."""
    result = bm25_retrieve(
        question="autoscaler pods",
        collection="alpha",
        vector_store=populated_store,
        k=5,
        doc_filter={"doc_name": ["vpa.md"]},
    )
    assert {c.doc_name for c in result.chunks} == {"vpa.md"}


def test_bm25_unknown_collection_raises_collection_not_found(populated_store):
    with pytest.raises(CollectionNotFound):
        bm25_retrieve(
            question="anything",
            collection="missing",
            vector_store=populated_store,
            k=5,
        )


def test_bm25_empty_when_doc_filter_excludes_everything(populated_store):
    result = bm25_retrieve(
        question="autoscaler",
        collection="alpha",
        vector_store=populated_store,
        k=5,
        doc_filter={"doc_name": ["does-not-exist.md"]},
    )
    assert result.chunks == []


# --- improved_retrieve -------------------------------------------------------


def test_improved_returns_at_most_k_chunks(populated_store, fake_embedder):
    result = improved_retrieve(
        question="autoscaler",
        collection="alpha",
        vector_store=populated_store,
        embedder=fake_embedder,
        k=2,
    )
    assert result.strategy == "improved"
    assert len(result.chunks) <= 2


def test_improved_recovers_keyword_match(populated_store, fake_embedder):
    """Even when the fake embedder makes vector retrieval random, the
    BM25 component should pull the obvious keyword match (hpa.md) into
    the fused candidate pool, and MMR should keep it."""
    result = improved_retrieve(
        question="horizontal pod autoscaler scaling",
        collection="alpha",
        vector_store=populated_store,
        embedder=fake_embedder,
        k=3,
    )
    doc_names = {c.doc_name for c in result.chunks}
    assert "hpa.md" in doc_names


def test_improved_respects_doc_filter(populated_store, fake_embedder):
    result = improved_retrieve(
        question="autoscaler",
        collection="alpha",
        vector_store=populated_store,
        embedder=fake_embedder,
        k=5,
        doc_filter={"doc_name": ["hpa.md", "vpa.md"]},
    )
    assert {c.doc_name for c in result.chunks} <= {"hpa.md", "vpa.md"}


def test_improved_unknown_collection_raises(populated_store, fake_embedder):
    with pytest.raises(CollectionNotFound):
        improved_retrieve(
            question="anything",
            collection="missing",
            vector_store=populated_store,
            embedder=fake_embedder,
            k=5,
        )


def test_improved_chunks_have_query_relevance_scores(populated_store, fake_embedder):
    """After MMR, ``score`` is the cosine similarity to the query, not
    the internal MMR score. It should be a finite float in [-1, 1]."""
    result = improved_retrieve(
        question="autoscaler",
        collection="alpha",
        vector_store=populated_store,
        embedder=fake_embedder,
        k=3,
    )
    for chunk in result.chunks:
        assert -1.0 <= chunk.score <= 1.0

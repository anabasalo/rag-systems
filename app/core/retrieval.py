"""Retrieval strategies.

Phase 2 introduces the ``basic`` strategy: pure dense (cosine) top-K.
Phase 3 will add ``improved`` (hybrid BM25 + vector + MMR).

The function takes the embedder and vector store as parameters so it
is unit-testable without a network call. See ADR 0005 for how
``doc_filter`` maps to ChromaDB's metadata ``where`` clause.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.embedders import Embedder
from app.core.exceptions import CollectionNotFound
from app.db.vector_store import RetrievedChunk, VectorStore


@dataclass(frozen=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    strategy: str


def basic_retrieve(
    *,
    question: str,
    collection: str,
    vector_store: VectorStore,
    embedder: Embedder,
    k: int = 5,
    doc_filter: dict | None = None,
) -> RetrievalResult:
    """Run a top-K cosine-similarity retrieval inside a single collection.

    Raises ``CollectionNotFound`` if the collection does not exist.
    """
    if not vector_store.collection_exists(collection):
        raise CollectionNotFound(collection)

    where = build_where_clause(doc_filter)
    has_tag_filter = bool(doc_filter and doc_filter.get("tags"))

    # Tags are stored as a CSV string in metadata (see ADR 0005 / data model
    # doc), so we cannot express a tag-membership filter as a Chroma `where`
    # operator. We over-fetch and post-filter in Python instead.
    fetch_k = k * 3 if has_tag_filter else k

    query_embedding = embedder.embed([question])[0]
    chunks = vector_store.query(
        collection=collection,
        embedding=query_embedding,
        k=fetch_k,
        where=where,
    )

    if has_tag_filter:
        tags = doc_filter.get("tags") or []
        chunks = post_filter_by_tags(chunks, tags)[:k]

    return RetrievalResult(chunks=chunks, strategy="basic")


def build_where_clause(doc_filter: dict | None) -> dict | None:
    """Translate the API-level ``doc_filter`` into a Chroma ``where`` clause.

    Currently encodes only ``doc_name`` natively. ``tags`` is handled by
    ``post_filter_by_tags`` below.
    """
    if not doc_filter:
        return None

    clauses: list[dict] = []

    doc_names = doc_filter.get("doc_name")
    if doc_names:
        clauses.append({"doc_name": {"$in": list(doc_names)}})

    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def post_filter_by_tags(
    chunks: Sequence[RetrievedChunk],
    tags: Sequence[str],
) -> list[RetrievedChunk]:
    """Keep chunks whose CSV-encoded ``tags`` metadata intersects ``tags``."""
    if not tags:
        return list(chunks)
    target = {t.strip() for t in tags if t.strip()}
    out: list[RetrievedChunk] = []
    for chunk in chunks:
        raw = str(chunk.metadata.get("tags", ""))
        chunk_tags = {t.strip() for t in raw.split(",") if t.strip()}
        if chunk_tags & target:
            out.append(chunk)
    return out

"""Retrieval strategies.

Two strategies live here:

- ``basic``  — dense (cosine) top-K. Phase 2.
- ``improved`` — hybrid BM25 + dense fused with Reciprocal Rank Fusion,
  then re-ranked with Maximal Marginal Relevance for diversity. Phase 3.

Functions take the embedder and vector store as parameters so they are
unit-testable without network calls. See ADR 0005 for how ``doc_filter``
maps to ChromaDB's metadata ``where`` clause.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

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


# --- BM25 (sparse / keyword) retrieval ---------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase word-level tokenization shared by query and corpus.

    Deliberately simple: BM25's strength is exact-term matching, so a
    consistent and predictable tokenizer matters more than linguistic
    sophistication. No stemming, no stopword removal — both can hurt
    technical queries (e.g. "the K" stripped from "the Kubernetes").
    """
    return [m.group(0).lower() for m in _TOKEN_RE.finditer(text)]


def bm25_retrieve(
    *,
    question: str,
    collection: str,
    vector_store: VectorStore,
    k: int = 5,
    doc_filter: dict | None = None,
) -> RetrievalResult:
    """Top-K BM25 retrieval over the chunks in ``collection``.

    The BM25 index is rebuilt per call from the collection's chunks. This
    is intentional: it keeps the system stateless and avoids a second
    persistence layer to keep in sync with Chroma. For a few hundred to a
    few thousand chunks it is fast (single-digit ms) and predictable.
    """
    if not vector_store.collection_exists(collection):
        raise CollectionNotFound(collection)

    where = build_where_clause(doc_filter)
    has_tag_filter = bool(doc_filter and doc_filter.get("tags"))

    candidates = vector_store.get_all_chunks(collection=collection, where=where)
    if has_tag_filter:
        candidates = post_filter_by_tags(candidates, doc_filter.get("tags") or [])

    if not candidates:
        return RetrievalResult(chunks=[], strategy="bm25")

    from rank_bm25 import BM25Okapi

    corpus_tokens = [tokenize(c.text) for c in candidates]
    bm25 = BM25Okapi(corpus_tokens)
    scores = bm25.get_scores(tokenize(question))

    ranked = sorted(
        zip(candidates, scores, strict=True),
        key=lambda pair: pair[1],
        reverse=True,
    )

    out: list[RetrievedChunk] = []
    for chunk, score in ranked[:k]:
        out.append(replace(chunk, score=float(score)))
    return RetrievalResult(chunks=out, strategy="bm25")


# --- Reciprocal Rank Fusion --------------------------------------------------


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[RetrievedChunk]],
    k_rrf: int = 60,
) -> list[RetrievedChunk]:
    """Fuse multiple ranked lists into one using Reciprocal Rank Fusion.

    For each chunk *c* and each ranking *r* containing *c* at position
    ``rank(c, r)`` (1-indexed), the fused score is::

        rrf(c) = sum over r of 1 / (k_rrf + rank(c, r))

    The ``k_rrf`` constant (default 60) damps the contribution of low-rank
    items; the value comes from Cormack et al. (2009) and works well in
    practice. Score scales of the input rankings are *not* used — only
    ranks — which is why RRF is so robust across mismatched scorers
    (e.g. cosine in [0, 1] vs. unbounded BM25).

    The returned list contains each unique chunk once, sorted by fused
    score descending. ``score`` on each chunk is set to its RRF score so
    downstream code can inspect it.
    """
    fused: dict[str, tuple[RetrievedChunk, float]] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            contribution = 1.0 / (k_rrf + rank)
            if chunk.chunk_id in fused:
                existing_chunk, existing_score = fused[chunk.chunk_id]
                fused[chunk.chunk_id] = (existing_chunk, existing_score + contribution)
            else:
                fused[chunk.chunk_id] = (chunk, contribution)

    items = sorted(fused.values(), key=lambda pair: pair[1], reverse=True)
    return [replace(chunk, score=float(score)) for chunk, score in items]


# --- Maximal Marginal Relevance ----------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def mmr_rerank(
    *,
    query_embedding: Sequence[float],
    candidates: Sequence[RetrievedChunk],
    candidate_embeddings: Sequence[Sequence[float]],
    k: int,
    lambda_mult: float = 0.5,
) -> list[RetrievedChunk]:
    """Re-rank ``candidates`` for the relevance/diversity trade-off.

    Implements Carbonell & Goldstein (1998): pick chunks one at a time,
    each turn maximizing::

        lambda * sim(c, query) - (1 - lambda) * max_{c' in selected} sim(c, c')

    - ``lambda_mult = 1.0`` recovers a pure relevance ranking.
    - ``lambda_mult = 0.0`` ignores the query and just spreads the
      selection across the candidate set.
    - The default ``0.5`` balances the two and tends to surface a chunk
      from each *aspect* of the answer rather than three near-duplicates.

    Caller must ensure ``len(candidates) == len(candidate_embeddings)``
    and that ``query_embedding`` lives in the same vector space.
    """
    if not candidates or k <= 0:
        return []
    if len(candidates) != len(candidate_embeddings):
        raise ValueError("candidates and candidate_embeddings must align")

    # Pre-compute query similarities once.
    query_sim = [_cosine(query_embedding, emb) for emb in candidate_embeddings]

    selected_idx: list[int] = []
    # List (not set) so iteration order is the input order. Important for
    # deterministic tie-breaking in tests and for the calling code.
    remaining: list[int] = list(range(len(candidates)))

    while remaining and len(selected_idx) < k:
        best_idx = None
        best_score = -math.inf
        for i in remaining:
            if not selected_idx:
                diversity_penalty = 0.0
            else:
                diversity_penalty = max(
                    _cosine(candidate_embeddings[i], candidate_embeddings[j]) for j in selected_idx
                )
            mmr_score = lambda_mult * query_sim[i] - (1.0 - lambda_mult) * diversity_penalty
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i
        assert best_idx is not None
        selected_idx.append(best_idx)
        remaining.remove(best_idx)

    out: list[RetrievedChunk] = []
    for i in selected_idx:
        # Replace the score with the query-relevance cosine so downstream
        # code (the prompt, the API response) gets a meaningful number,
        # not the internal MMR score.
        out.append(replace(candidates[i], score=float(query_sim[i])))
    return out


# --- Improved (hybrid + MMR) retrieval ---------------------------------------


def improved_retrieve(
    *,
    question: str,
    collection: str,
    vector_store: VectorStore,
    embedder: Embedder,
    k: int = 5,
    doc_filter: dict | None = None,
    fetch_k: int = 20,
    rrf_k: int = 60,
    mmr_lambda: float = 0.5,
) -> RetrievalResult:
    """Hybrid retrieval: dense ⊕ BM25, fused with RRF, re-ranked with MMR.

    Steps:

    1. Run vector top-N (``N = fetch_k``) and BM25 top-N independently.
    2. Fuse the two rankings with Reciprocal Rank Fusion.
    3. Take the top ``fetch_k`` of the fused list as the candidate pool.
    4. Re-rank that pool with MMR using the query embedding and the
       candidates' stored embeddings, returning ``k`` final chunks.

    Step 4 is what gives the strategy its character: vector + BM25 alone
    often returns near-duplicate chunks (especially when one document
    repeats a phrase). MMR spreads the selection.
    """
    if not vector_store.collection_exists(collection):
        raise CollectionNotFound(collection)

    where = build_where_clause(doc_filter)
    has_tag_filter = bool(doc_filter and doc_filter.get("tags"))

    query_embedding = embedder.embed([question])[0]

    # 1a. Vector ranking -- over-fetch so RRF has material to work with.
    vector_fetch = fetch_k * 3 if has_tag_filter else fetch_k
    vector_chunks = vector_store.query(
        collection=collection,
        embedding=query_embedding,
        k=vector_fetch,
        where=where,
    )
    if has_tag_filter:
        vector_chunks = post_filter_by_tags(vector_chunks, doc_filter.get("tags") or [])
    vector_chunks = vector_chunks[:fetch_k]

    # 1b. BM25 ranking over the same filtered candidate pool.
    bm25_result = bm25_retrieve(
        question=question,
        collection=collection,
        vector_store=vector_store,
        k=fetch_k,
        doc_filter=doc_filter,
    )

    if not vector_chunks and not bm25_result.chunks:
        return RetrievalResult(chunks=[], strategy="improved")

    # 2. Reciprocal Rank Fusion.
    fused = reciprocal_rank_fusion(
        [vector_chunks, bm25_result.chunks],
        k_rrf=rrf_k,
    )
    pool = fused[:fetch_k]
    if not pool:
        return RetrievalResult(chunks=[], strategy="improved")

    # 3. Fetch embeddings for the pool. We could keep them from vector_chunks,
    # but BM25-only hits would be missing — pull them all in one Chroma read.
    pool_ids = [c.chunk_id for c in pool]
    embedded = vector_store.get_all_chunks(
        collection=collection,
        ids=pool_ids,
        include_embeddings=True,
    )
    by_id = {c.chunk_id: c for c in embedded}

    aligned_candidates: list[RetrievedChunk] = []
    aligned_embeddings: list[list[float]] = []
    for chunk in pool:
        full = by_id.get(chunk.chunk_id)
        if full is None:
            continue
        embedding = full.metadata.get("_embedding")
        if not embedding:
            continue
        aligned_candidates.append(chunk)
        aligned_embeddings.append(list(embedding))

    if not aligned_candidates:
        return RetrievalResult(chunks=[], strategy="improved")

    # 4. MMR re-rank to the final K.
    final = mmr_rerank(
        query_embedding=query_embedding,
        candidates=aligned_candidates,
        candidate_embeddings=aligned_embeddings,
        k=k,
        lambda_mult=mmr_lambda,
    )

    return RetrievalResult(chunks=final, strategy="improved")

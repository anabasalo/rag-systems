"""Phase 3 retrieval-primitive tests.

These tests pin the *behavior* of BM25 ranking, Reciprocal Rank Fusion,
and MMR re-ranking on small, hand-crafted inputs. They are pure unit
tests: no ChromaDB, no real embedder, no FastAPI.
"""

from __future__ import annotations

from app.core.retrieval import (
    mmr_rerank,
    reciprocal_rank_fusion,
    tokenize,
)
from app.db.vector_store import RetrievedChunk


def _chunk(chunk_id: str, text: str = "", doc_name: str = "doc.md") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_name=doc_name,
        chunk_index=0,
        text=text,
        score=0.0,
        metadata={"doc_name": doc_name},
    )


# --- tokenize ----------------------------------------------------------------


def test_tokenize_lowercases_and_splits_on_punctuation():
    assert tokenize("Kubernetes' HPA auto-scales pods!") == [
        "kubernetes",
        "hpa",
        "auto",
        "scales",
        "pods",
    ]


def test_tokenize_keeps_alphanumeric_runs():
    assert tokenize("v1.2 + http2") == ["v1", "2", "http2"]


# --- Reciprocal Rank Fusion --------------------------------------------------


def test_rrf_promotes_chunks_ranked_high_in_both_lists():
    """A chunk ranked #1 in both lists should beat one ranked #1 in only one."""
    a = _chunk("a")
    b = _chunk("b")
    c = _chunk("c")

    # `a` is rank 1 in both → 2 * 1/61 ≈ 0.0328
    # `b` is rank 2 in one, rank 3 in the other → 1/62 + 1/63 ≈ 0.0320
    # `c` is rank 3 in one, rank 2 in the other → 1/63 + 1/62 ≈ 0.0320
    fused = reciprocal_rank_fusion(
        [
            [a, b, c],
            [a, c, b],
        ],
        k_rrf=60,
    )

    ids = [chunk.chunk_id for chunk in fused]
    assert set(ids) == {"a", "b", "c"}
    assert ids[0] == "a"


def test_rrf_consistent_mid_rank_beats_one_top_one_missing():
    """Being present in *both* rankings, even at mid rank, beats being
    top in one and missing from the other (for small lists)."""
    consistent = _chunk("consistent")
    only_in_one = _chunk("only_in_one")
    filler1, filler2 = _chunk("f1"), _chunk("f2")

    fused = reciprocal_rank_fusion(
        [
            [only_in_one, consistent, filler1],  # consistent at rank 2
            [filler2, consistent, filler1],  # consistent at rank 2
        ],
        k_rrf=60,
    )

    ids = [c.chunk_id for c in fused]
    # consistent: 2 * 1/62 ≈ 0.0323
    # only_in_one: 1 * 1/61 ≈ 0.0164
    assert ids.index("consistent") < ids.index("only_in_one")


def test_rrf_returns_unique_chunks_with_score_set():
    a = _chunk("a")
    fused = reciprocal_rank_fusion([[a], [a]], k_rrf=60)
    assert len(fused) == 1
    # Score should equal 2 * 1/(60+1) since the chunk appears at rank 1 twice.
    assert abs(fused[0].score - 2 / 61) < 1e-9


def test_rrf_handles_empty_rankings():
    a = _chunk("a")
    fused = reciprocal_rank_fusion([[a], []], k_rrf=60)
    assert [c.chunk_id for c in fused] == ["a"]

    fused = reciprocal_rank_fusion([[], []], k_rrf=60)
    assert fused == []


def test_rrf_top_of_one_list_beats_bottom_of_other():
    """A chunk ranked #1 in one source should beat a chunk ranked #5 in another."""
    top1 = _chunk("top1")
    bottom5 = _chunk("bottom5")
    filler = [_chunk(f"f{i}") for i in range(4)]

    fused = reciprocal_rank_fusion(
        [
            [top1] + filler,
            filler + [bottom5],
        ],
        k_rrf=60,
    )
    ids = [c.chunk_id for c in fused]
    assert ids.index("top1") < ids.index("bottom5")


# --- MMR ---------------------------------------------------------------------


def test_mmr_prefers_diversity_over_repeating_a_top_match():
    """Three unit vectors all equally relevant to the query (cosine=0.8),
    but two of them are near-duplicates of each other and one points in a
    different direction. MMR should pick one of the dups + the different
    one, never both dups."""
    query = [1.0, 0.0, 0.0]
    near_dup_a = _chunk("dup_a")
    near_dup_b = _chunk("dup_b")
    different = _chunk("different")

    candidates = [near_dup_a, near_dup_b, different]
    embeddings = [
        [0.8, 0.6, 0.0],  # |.|=1, sim_q=0.8
        [0.8, 0.5, 0.331],  # |.|=1, sim_q=0.8, sim(dup_a)=0.94
        [0.8, 0.0, 0.6],  # |.|=1, sim_q=0.8, sim(dup_a)=0.64
    ]

    selected = mmr_rerank(
        query_embedding=query,
        candidates=candidates,
        candidate_embeddings=embeddings,
        k=2,
        lambda_mult=0.5,
    )
    ids = [c.chunk_id for c in selected]
    assert "different" in ids
    # The first pick is whichever dup wins on raw relevance + iteration
    # order; the second must NOT be the other near-duplicate.
    assert not (ids[0].startswith("dup_") and ids[1].startswith("dup_"))


def test_mmr_lambda_one_recovers_pure_relevance_ranking():
    query = [1.0, 0.0]
    cands = [_chunk("a"), _chunk("b"), _chunk("c")]
    embs = [
        [0.50, 0.50],  # cosine ~ 0.707
        [0.99, 0.10],  # cosine ~ 0.99 -- most relevant
        [0.90, 0.30],  # cosine ~ 0.95
    ]

    selected = mmr_rerank(
        query_embedding=query,
        candidates=cands,
        candidate_embeddings=embs,
        k=3,
        lambda_mult=1.0,
    )
    ids = [c.chunk_id for c in selected]
    # Order strictly by relevance: b (0.99) > c (0.95) > a (0.71)
    assert ids == ["b", "c", "a"]


def test_mmr_returns_at_most_k():
    query = [1.0, 0.0]
    cands = [_chunk(f"c{i}") for i in range(5)]
    embs = [[0.9 - 0.1 * i, 0.1 * i] for i in range(5)]

    selected = mmr_rerank(
        query_embedding=query,
        candidates=cands,
        candidate_embeddings=embs,
        k=3,
        lambda_mult=0.5,
    )
    assert len(selected) == 3


def test_mmr_empty_inputs_return_empty_list():
    assert (
        mmr_rerank(
            query_embedding=[1.0, 0.0],
            candidates=[],
            candidate_embeddings=[],
            k=5,
        )
        == []
    )


def test_mmr_score_attached_is_query_cosine_not_internal_score():
    query = [1.0, 0.0]
    cands = [_chunk("a")]
    embs = [[1.0, 0.0]]
    selected = mmr_rerank(
        query_embedding=query,
        candidates=cands,
        candidate_embeddings=embs,
        k=1,
        lambda_mult=0.5,
    )
    assert len(selected) == 1
    # cosine(query, [1, 0]) == 1.0
    assert abs(selected[0].score - 1.0) < 1e-9

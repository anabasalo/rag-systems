# Phase 3 — Concepts

Plain-language explanations of what BM25 retrieves, what MMR rearranges,
and why we glue them together with Reciprocal Rank Fusion.

## Sparse vs. dense retrieval

Two fundamentally different ways to "find relevant chunks":

**Sparse retrieval** — represent each chunk as a long vector indexed by
words from a vocabulary. Most entries are zero (the chunk does not
contain that word); a few entries carry weights derived from word
frequency. Matching is *lexical*: the query's words have to overlap
with the chunk's words.

> Example: query `"horizontal pod autoscaler"` matches a chunk
> containing those exact words; it does not match `"automatic scaling
> of replicas based on CPU"`.

**Dense retrieval** — represent each chunk as a short (384-dim in our
project) vector produced by a neural network. The vector encodes
*meaning*, not words. Two chunks that say the same thing in different
words land near each other in the vector space.

> Example: query `"horizontal pod autoscaler"` matches `"automatic
> scaling of replicas based on CPU"` because the embedder maps both
> to similar regions of the space.

Each approach fails differently:

| Failure mode | Sparse (BM25) | Dense (vector) |
| --- | --- | --- |
| Synonym / paraphrase | misses ("scale up" vs. "increase replicas") | finds |
| Exact identifier match (`HPA`, `--max-replicas`, `kube-controller-manager`) | finds | sometimes misses |
| Out-of-vocabulary term | depends | depends on training data |
| Domain-specific jargon | finds if user uses the same word | finds if the embedder has seen the domain |
| Long compound queries | works on the keywords | sometimes drowned out by less informative tokens |

The pragmatic conclusion of 50 years of IR research is: **use both**.
That's what Phase 3 does.

## BM25 in 60 seconds

BM25 ("Best Matching 25") is the standard sparse ranking function.
For each query term *q* and each chunk *d*, it computes:

$$
\text{score}(d, q) = \sum_{q \in \text{query}} \text{IDF}(q) \cdot \frac{f(q, d) \cdot (k_1 + 1)}{f(q, d) + k_1 \cdot \left(1 - b + b \cdot \frac{|d|}{\text{avgdl}}\right)}
$$

You don't need to implement that — `rank_bm25` does — but the three
ideas are worth recognizing:

1. **TF (term frequency).** A chunk that mentions the query word more
   often is more relevant. (`f(q, d)` above.)
2. **IDF (inverse document frequency).** A query word that's rare
   across the corpus is more informative than a common one. (Hits on
   `"the"` should not move scores.)
3. **Length normalization.** Long chunks should not win just by being
   long. The `b` parameter controls how aggressively to discount them.

`k_1` (default ~1.5) and `b` (default ~0.75) are tunable; the
defaults from `rank_bm25` are sensible for our chunk sizes and we
have not changed them.

In the project, `tokenize()` in `app/core/retrieval.py` is the
shared tokenizer. It is deliberately simple — lowercase + split on
non-alphanumeric — because BM25's strength is *exact* match. Stemming
or stopword removal would help recall but hurt precision on
technical queries, where the user's literal phrasing usually matters.

## Why hybrid (BM25 + vector) actually wins

Consider the question `"What does kube-proxy do?"` against a Kubernetes
corpus.

- The vector retriever may return chunks about networking,
  service discovery, iptables — semantically related, but not
  *the* chunk that defines `kube-proxy`.
- BM25 will pull any chunk that contains the literal string
  `kube-proxy`, regardless of what the chunk explains around it.

Neither alone is great. Together, you get:

- the chunk that explicitly defines `kube-proxy` (BM25 hit), AND
- the chunks that explain *why* kube-proxy exists (vector hits).

This is the empirical observation behind every "hybrid search beats
either alone" benchmark since around 2020.

## Reciprocal Rank Fusion (RRF)

We have two ranked lists and need one. The naive thing is to combine
the *scores*: `final = α * cosine + (1-α) * bm25_score`. That breaks
because:

- **Different scales.** Cosine sits in `[-1, 1]`. BM25 is unbounded
  and its absolute values depend on the corpus.
- **Different distributions.** BM25 score 12 vs. 8 might mean a big
  difference; cosine 0.91 vs. 0.89 might mean nothing.
- **Tuning hell.** Every new corpus needs a new α.

RRF (Cormack et al., 2009) sidesteps the entire problem by **using
ranks, not scores**. For each chunk *d* and each ranking *r*:

$$
\text{rrf}(d) = \sum_r \frac{1}{k + \text{rank}(d, r)}
$$

A chunk in two rankings gets two contributions; one in only one
ranking gets one. The constant `k` (we use 60, the value from the
original paper) damps the contribution of low-rank items so the top
of each list dominates. No tuning per corpus.

> **Why does this work?** Because for ranked retrieval, *order* is the
> reliable signal across heterogeneous scorers — actual scores are
> not.

We use RRF in [`reciprocal_rank_fusion`](../../app/core/retrieval.py).
It is six lines of real code; the unit tests in
[`tests/test_retrieval.py`](../../tests/test_retrieval.py) verify the
behavior on small hand-crafted rankings.

## Maximal Marginal Relevance (MMR)

After RRF you have a fused ranking, but it can still contain
near-duplicates: vector and BM25 might both return *the same chunk*
twice (deduplicated by RRF, fine), but they can also both return two
chunks of the same paragraph, or two highly similar paragraphs from
the same document. Returning all near-duplicates to the LLM wastes
context tokens.

MMR (Carbonell & Goldstein, 1998) re-ranks the candidate pool by
trading off relevance to the query against diversity from chunks
already picked:

$$
\text{MMR}(c) = \lambda \cdot \text{sim}(c, q) - (1 - \lambda) \cdot \max_{c' \in S} \text{sim}(c, c')
$$

where *S* is the set of chunks already selected. Pick the `c` with
the highest MMR score; add it to *S*; repeat.

- `λ = 1.0` recovers a pure relevance ranking.
- `λ = 0.0` ignores the query and just spreads the picks across the
  candidate pool.
- The default in this project is `0.5` — balance the two.

Practical effect: in the candidate pool of size 20 from RRF, if two
chunks are very similar to each other, MMR will pick one, then prefer
chunks that are *unlike* it for the next slots. The final 5-chunk
list spans more of the relevant material.

We use MMR in [`mmr_rerank`](../../app/core/retrieval.py). The unit
tests verify the relevance-vs-diversity trade-off on a tiny vector
example you can read in 30 seconds.

## Candidate-pool sizing (the `fetch_k` constant)

`improved_retrieve` over-fetches: it runs both retrievers with a
larger `fetch_k` than the final `k`, fuses, then MMR cuts down to `k`.
Why?

- If we ran each retriever with `fetch_k = k` (final K), the pool
  before MMR would be at most `2k` chunks (with full overlap, just
  `k`). MMR has nothing to choose from — its diversity step is a
  no-op.
- With `fetch_k = 20` and final `k = 5`, MMR picks 5 from 20 — that
  is where the diversity benefit appears.
- Going higher (`fetch_k = 100`) makes BM25 corpus rebuild, the
  Chroma read, and the MMR loop all proportionally more expensive,
  with diminishing returns.

The default `fetch_k = 20` is the smallest value at which MMR has
real freedom to choose without paying a noticeable latency cost.

## The empty-context fallback still applies

After `improved_retrieve` returns its `k` chunks, the same
`similarity_floor` from Phase 2 is applied (in `app/api/query.py`).
If no chunk passes the floor, we still short-circuit with the safe
answer and never call the LLM. The improved strategy gets *more*
candidates into the pool but does not lower the bar for what counts
as a relevant answer — that is on purpose.

## Why we pin the score in MMR output

Inside `mmr_rerank`, the per-iteration score we use to pick chunks is
the MMR formula above (with the diversity penalty). But that score
is meaningless to API callers — it can be negative, it depends on
λ, and it depends on the order chunks were selected.

Instead, we attach the **query-relevance cosine** (`sim(c, q)`) as
the chunk's `score` in the result. That number is comparable to what
`basic` returns (also a cosine) and is what the API surfaces in
`sources[].score`. The MMR ordering is preserved by the *order* of
the result list, which is what callers actually consume.

Pinning this is one test:
[`test_mmr_score_attached_is_query_cosine_not_internal_score`](../../tests/test_retrieval.py).

## What "improved" does NOT do

To set expectations:

- **No query expansion.** We do not paraphrase the question or
  generate synonyms. (See `alternatives.md` for what that would buy.)
- **No re-ranking with a cross-encoder.** Cross-encoders read the
  query and chunk together and produce a relevance score; they
  generally beat MMR on quality but cost ~10ms per chunk and require
  an extra model. For free, fast, and good-enough we picked MMR.
- **No learning to rank.** We do not adjust weights based on labelled
  feedback. Phase 4's evaluation will tell us whether we should.
- **No multi-hop retrieval.** Each query is one shot; we do not let
  the LLM ask follow-up retrievals. Agentic RAG is a Phase 5+ topic.

These are real limitations. The "improved" strategy is *better* than
basic on the typical retrieval-quality axes; it is not the
state-of-the-art ceiling.

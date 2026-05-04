# Phase 3 — Alternatives

For each design choice in the improved retrieval pipeline, this
document records the alternatives that were considered, the trade-off
that was made, and the conditions under which the alternative would
have been the better answer.

## Alternative 1 — How to combine BM25 and vector rankings

We chose **Reciprocal Rank Fusion**. The serious alternatives:

### Weighted score normalization

```
final = α * z_norm(cosine) + (1 - α) * z_norm(bm25_score)
```

Where `z_norm` is a per-query z-score. Conceptually appealing,
practically a tuning nightmare:

- Cosine sits in `[-1, 1]`; BM25 is unbounded and corpus-dependent.
  Without normalization, BM25 dominates on long queries and gets
  drowned out on short queries.
- The "right" α depends on the corpus, the query type, and even the
  user's wording. A value tuned on technical questions does poorly on
  conversational ones.
- Adding a third retriever (say, a learned cross-encoder) means
  re-tuning α and β jointly.

RRF avoids all of this by ignoring scores. The same `k_rrf=60`
constant works across corpora.

### Min-max normalization

```
final = α * (cosine - cos_min) / (cos_max - cos_min) +
        (1-α) * (bm25 - bm25_min) / (bm25_max - bm25_min)
```

Better than raw scores but still suffers from **distributional drift**:
if today's query has BM25 scores `[0.01, 0.02, 12.0, 12.1]` and
tomorrow's has `[0.5, 0.6, 0.7, 0.8]`, min-max produces wildly
different rescalings even though the *relative ordering* is similar.

### CombSUM / CombMNZ

Older fusion methods. CombSUM adds normalized scores; CombMNZ
multiplies by the number of retrievers that returned the chunk.
Comparable to RRF on simple corpora; more sensitive to score
normalization on heterogeneous ones.

### Why RRF wins for this project

- Two-line implementation, ~20 lines including the docstring and
  edge cases.
- No tuning. Drop in a third retriever and it just works.
- Empirically competitive with more elaborate methods on academic
  benchmarks (Cormack et al., 2009).
- The result list has a meaningful order; the score is just a
  by-product.

The honest cost: RRF has no concept of *score margins*. If chunk A
beats chunk B by 0.99 vs. 0.05 in cosine and ties them in BM25 rank,
RRF treats them as nearly equal. That is a real loss of information,
and it is why production systems sometimes layer a cross-encoder on
top of an RRF stage. We did not, for the reasons in Alternative 2.

## Alternative 2 — How to re-rank the fused candidate pool

We chose **MMR**. The serious alternatives:

### Cross-encoder reranking (e.g. `BAAI/bge-reranker-base`)

The state-of-the-art "good baseline" for re-ranking. A cross-encoder
takes `(query, chunk)` together and outputs a relevance score; this
is more accurate than the bi-encoder embeddings we use for retrieval
because the model can attend across query and chunk simultaneously.

| Dimension | MMR | Cross-encoder |
| --- | --- | --- |
| Quality on relevance | medium | high |
| Quality on diversity | high (built-in) | none — needs MMR on top of it |
| Compute cost per query | ~ms (pure Python) | tens of ms per chunk × pool size; needs a model loaded |
| Memory footprint | none | another small model in RAM |
| Free / runs offline | yes | yes (the small models do) |
| Sensitive to chunk size | a little | a lot — most have a 512-token input limit |

For a project optimizing for *legibility and zero infra*, MMR was the
right pick. If retrieval quality is the bottleneck Phase 4 finds, the
right next move is to add a cross-encoder *after* MMR (or instead of
the relevance side of MMR), not to keep tuning MMR's λ.

### LLM-as-reranker

Ask Groq to read the candidate pool and pick the best ones. This
works surprisingly well but:

- **Doubles token spend** on every query.
- **Doubles latency.**
- **Couples retrieval to the LLM provider.** The system can no longer
  evaluate retrieval in isolation.

We rejected this for the same reasons we don't ask the LLM to
re-rank during ingestion.

### No re-ranking (pass RRF top-K straight to the LLM)

Simplest possible. Loses the diversity property — the LLM sees
near-duplicates. Acceptable for very small corpora; loses quickly to
MMR as the corpus grows.

We considered this and decided MMR's added complexity was small
enough that having it now (and *measuring* whether it helps in
Phase 4) was worth the ~30 lines of code.

### Learning-to-rank with labels

Train a model on (query, chunk, relevance_label) triples. State of
the art at internet companies; massive overkill for a 1-2 week study
project with no labelled data. Phase 4 will produce some labelled
data via RAGAS evaluation, but not enough to justify training a
ranker.

## Alternative 3 — Where to build the BM25 index

Three places we could have put the keyword index:

### (Picked) On-demand, per query, in memory

Each call to `bm25_retrieve` pulls all chunks from Chroma, tokenizes
them, builds `BM25Okapi`, scores once, throws the index away.

- ✅ Stateless. No second persistence layer to keep in sync.
- ✅ Always consistent with what's in Chroma.
- ❌ O(N × tokens) on every query. Fine at hundreds-to-thousands of
  chunks, slow at hundreds of thousands.
- ❌ The full Chroma read is the dominant cost.

### Persisted alongside Chroma

Build the BM25 index at ingest time; persist to disk. Update it on
ingest, delete entries on doc deletion.

- ✅ Sub-millisecond queries even on large corpora.
- ❌ Two indexes to keep in sync. Failure modes include "BM25 still
  has chunks we deleted from Chroma" and "BM25 missing chunks we
  added to Chroma". Both produce wrong answers silently.
- ❌ Extra code at the ingestion path; another thing to back up.

### A search engine that does both (e.g. Elasticsearch / OpenSearch)

The "real" answer at scale. Both BM25 and dense vectors are first-class
citizens in the same index, with ACID-ish writes and a query DSL.

- ✅ Production-ready.
- ❌ A heavyweight runtime dependency. Even the small Docker images
  are ~1 GB; the cluster topology is not a study-project concern.
- ❌ Replaces ChromaDB and forces a rewrite of `app/db/`.

The on-demand approach was the right pick for the project's stage.
ADR 0001 (vector store) discusses why ChromaDB is a deliberate
boundary — *not* the long-term answer for a real product. If/when
this project graduates to one, swapping `app/db/vector_store.py` for
an OpenSearch wrapper is the obvious migration path.

## Alternative 4 — Tokenization for BM25

We picked **lowercase + alphanumeric tokens, no stemming, no stopword
removal**. Other valid choices:

### Stem with Porter / Snowball

`autoscaling` → `autoscal`, `pods` → `pod`, etc. Improves recall when
the user's wording differs from the document's (`scales` vs.
`scaling`). Hurts precision on technical terms that look like English
words but aren't (`Pods` is *not* `pod`s in the linguistic sense).

For technical content where the user *probably* uses the same word
the docs do, the recall gain is small and the precision loss is real.

### Drop stopwords

Drop `the`, `a`, `is`, `of`. Speeds BM25 up on common queries by
ignoring high-IDF-low-information tokens. Modern BM25 already weights
those low via IDF, so the marginal benefit is small. The risk: real
queries sometimes hinge on a stopword (`"the K8s networking model"`
becomes ambiguous if `the` is dropped — though that one is fine —
but `"function in a function"` definitely needs both `in` and `a`
in some pathological queries).

### Subword tokenization (BPE / WordPiece)

What the embedder uses. Would let BM25 match `kube-proxy` against
`kubeproxy` (because they'd share subword tokens). In practice
sparse retrieval libraries don't ship BPE tokenizers; integrating
one is non-trivial; and we already have dense retrieval for the
"close-but-not-exact" case.

## Alternative 5 — Where MMR's λ is configured

Three options:

1. **Hard-coded in `improved_retrieve` (current).** Default 0.5.
   Simple, predictable.
2. **Settings field.** Add `mmr_lambda` to `app/config.py` and read
   it from the environment.
3. **Per-request parameter on `/query`.** Let callers send their own
   λ each time.

We chose **(1)** because:

- Phase 4 is going to *measure* whether 0.5 is right. Until then,
  knobs are noise.
- Per-request λ leaks an algorithm parameter into the API contract,
  which is the wrong layer.
- A settings field is easy to add later if Phase 4 finds the right
  value depends on the corpus.

If Phase 4's eval shows the optimal λ varies by corpus, option (2) is
the natural follow-up. Option (3) is almost never the right answer
for tunables — they belong in operator config, not the public API.

## Alternative 6 — Query expansion

We did not do query expansion. The contenders:

### LLM rephrasing

Ask a small LLM to rewrite the question in 2-3 ways before
retrieval (a.k.a. "Multi-Query Retriever" in some libraries).
Combine the retrieval results from each rewrite via RRF.

- ✅ Helps when the user's wording is unusual.
- ❌ Doubles or triples LLM cost per query.
- ❌ Latency adds up: a small-LLM rewrite is ~300ms.

### HyDE (Hypothetical Document Embeddings)

Ask the LLM to generate a *hypothetical answer*, embed that, search
with that embedding instead of the question's. Often improves vector
retrieval for short, ambiguous questions.

- ✅ Free with the same LLM you're already using.
- ❌ Same latency cost as LLM rephrasing.
- ❌ Generates a hypothetical answer *before* checking if the corpus
  contains one — a hallucination-shaped path through the system.

### Pseudo-relevance feedback (PRF)

Take the top chunks from the first retrieval, extract their most
distinctive terms, append those to the query, and retrieve again.
Classical IR technique that works without an LLM.

- ✅ No extra model needed.
- ❌ Slower (two retrievals per query).
- ❌ Amplifies whatever bias the first retrieval has — if it was
  wrong, PRF makes it more wrong.

For this phase, the simpler hybrid+MMR pipeline is enough material
to study and to evaluate. If Phase 4's eval shows recall is the
bottleneck on certain question types, query expansion is the obvious
next experiment.

## Alternative 7 — Returning both responses from `/compare` vs. a single ranking

`/compare` runs **both** strategies and returns both. We could have:

- Returned only `improved` and an A/B-test flag (server-side rotates).
  Useless for studying *why* improved is better.
- Returned a single "winning" answer chosen by some heuristic.
  Useless for the same reason — the user can't see the inputs.

The chosen design makes `/compare` a **tool for understanding**:
identical inputs, two outputs, side by side. That is exactly what we
need for Phase 4's eval (which will run both strategies on every
question in a benchmark) and for the demo.

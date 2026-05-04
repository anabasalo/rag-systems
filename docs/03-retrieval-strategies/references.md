# Phase 3 — References

Curated reading for the algorithms this phase introduces.

## Foundational papers

- **Robertson & Zaragoza, 2009 — *The Probabilistic Relevance
  Framework: BM25 and Beyond*.**
  https://www.cl.uni-heidelberg.de/courses/ws14/seminararbeiten/Robertson_Zaragoza_BM25_2009.pdf
  The canonical reference for BM25. Sections 2-3 derive the formula;
  Section 4 covers the parameter tuning we did *not* do (and why we
  got away with it).

- **Cormack, Clarke & Büttcher, 2009 — *Reciprocal Rank Fusion
  Outperforms Condorcet and Individual Rank Learning Methods*.**
  https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
  The paper that introduced and named RRF. The empirical result is
  short and convincing: a single tuning constant (k=60) outperforms
  a dozen score-fusion methods across TREC tracks. This is the
  paper our `reciprocal_rank_fusion` directly implements.

- **Carbonell & Goldstein, 1998 — *The Use of MMR, Diversity-Based
  Reranking for Reordering Documents and Producing Summaries*.**
  https://www.cs.cmu.edu/~jgc/publication/The_Use_MMR_Diversity_Based_LTMIR_1998.pdf
  The MMR paper. Originally proposed for *summarization* (pick
  sentences that cover all aspects of a document); the same formula
  works for ranking. Worth reading the introduction for the
  motivation: "the ten most relevant documents are often nine
  rephrasings of the same one".

- **Karpukhin et al., 2020 — *Dense Passage Retrieval for
  Open-Domain QA* (DPR).**
  https://arxiv.org/abs/2004.04906
  Already cited in Phase 2; revisit for Section 5, which compares
  BM25 and DPR head-to-head on QA datasets and shows neither
  dominates — a direct argument for the hybrid approach we use.

- **Lin & Ma, 2021 — *A Few Brief Notes on DeepImpact, COIL, and a
  Conceptual Framework for Information Retrieval Techniques*.**
  https://arxiv.org/abs/2106.14807
  A taxonomy paper. The figure on page 2 organizes BM25, dense
  retrieval, and learned-sparse retrievers under one framework and
  is the clearest "where does X fit" diagram I know.

## Practical guides

- **Pinecone — *Hybrid Search*.**
  https://www.pinecone.io/learn/hybrid-search/
  Pinecone-specific but the conceptual sections are vendor-neutral
  and discuss the same RRF/score-fusion trade-offs we resolved in
  `alternatives.md`.

- **Weaviate — *Hybrid Search*.**
  https://weaviate.io/blog/hybrid-search-explained
  Includes a worked example of how the rank-vs-score-fusion
  decision plays out on a real corpus.

- **Anthropic — *Contextual Retrieval*.**
  https://www.anthropic.com/news/contextual-retrieval
  A good reminder that retrieval improvements compound. Anthropic's
  result: BM25 + embeddings + reranker outperforms each alone, in
  that order. The same shape as our pipeline.

- **Microsoft Research — *Generative Retrieval and Reranking with
  LLMs* (blog).**
  Useful counterpoint that frames query rewriting / HyDE as a
  contender for the same role MMR plays here. We chose MMR; this is
  good context for *why one might not*.

## Library references

- **`rank_bm25` source.**
  https://github.com/dorianbrown/rank_bm25
  The library is ~200 lines. Reading `BM25Okapi.get_scores` is the
  fastest way to confirm what BM25 actually does.

- **ChromaDB `where` clause syntax.**
  https://docs.trychroma.com/usage-guide#using-where-filters
  The metadata filter we use to scope `bm25_retrieve` to a
  `doc_filter`. Note `$in`, `$and`, and the lack of substring
  matching — that's why our `tags` filter is post-applied in Python.

- **FastAPI dependency overrides for tests.**
  https://fastapi.tiangolo.com/advanced/testing-dependencies/
  How `tests/conftest.py::client` swaps the real generator for a
  fake. This pattern made `/compare` testable without a live LLM.

## Books and courses

- **Manning, Raghavan & Schütze — *Introduction to Information
  Retrieval*.**
  https://nlp.stanford.edu/IR-book/
  Free online. Chapter 11 (Probabilistic IR) covers the math behind
  BM25. Chapter 6 covers vector-space retrieval. Chapter 8 covers
  evaluation metrics that Phase 4 will need.

- **Lin, Nogueira & Yates — *Pretrained Transformers for Text
  Ranking: BERT and Beyond*.**
  https://arxiv.org/abs/2010.06467
  Open-access survey of neural retrieval. Section 3 covers
  bi-encoders (what we use); Section 4 covers cross-encoders (what
  we deliberately skipped — see `alternatives.md`).

## Adjacent reading worth a skim

- **Gao et al., 2022 — *Precise Zero-Shot Dense Retrieval without
  Relevance Labels* (HyDE).**
  https://arxiv.org/abs/2212.10496
  The query-expansion alternative we did not use. Worth knowing
  what it buys (and at what cost) before Phase 4.

- **Khattab & Zaharia, 2020 — *ColBERT: Efficient and Effective
  Passage Search via Contextualized Late Interaction over BERT*.**
  https://arxiv.org/abs/2004.12832
  An entirely different architecture (token-level dense matching).
  Currently the strongest open-source baseline; an order of
  magnitude more expensive than what we built. Important context
  for the ceiling of what hybrid + MMR can achieve.

- **Cormack et al., 2017 — *Efficient and Effective Spam Filtering
  and Re-Ranking for Large Web Datasets*.**
  https://arxiv.org/abs/1710.10396
  Same first author as the RRF paper, applying the same fusion
  ideas at industrial scale. Useful sanity check that RRF holds up
  outside the academic-benchmark setting.

## Project artifacts that double as references

- [`docs/00-design/03-architecture.md`](../00-design/03-architecture.md)
  — the layered design that lets us add `improved_retrieve` without
  touching the API or generation layers.
- [`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md)
  — the source of truth for `/query` and `/compare` shapes.
- [`docs/00-design/adrs/0001-vector-db-chromadb.md`](../00-design/adrs/0001-vector-db-chromadb.md)
  — Chroma's `where`/`get(ids=...)` API is the reason BM25 corpus
  fetch and MMR embedding fetch are both single calls.
- [`tests/test_retrieval.py`](../../tests/test_retrieval.py) — every
  property the algorithms are claimed to have is pinned by a named
  test. Reading the test names is an executable summary of the
  retrieval contract.
- [`tests/test_retrieval_integration.py`](../../tests/test_retrieval_integration.py)
  — the BM25-and-improved tests against a real ChromaDB show that
  the algorithms behave correctly when they actually have a corpus.

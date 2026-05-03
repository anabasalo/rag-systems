# Phase 1 — References

Curated reading. Each entry has a one-line "why read this".

## Vector stores and ANN search

- **ChromaDB documentation** — [docs.trychroma.com](https://docs.trychroma.com/)
  Source of truth for the API we wrap in `app/db/vector_store.py`.
- **HNSW: Efficient and robust approximate nearest neighbor search** — Malkov & Yashunin, 2016 ([arXiv 1603.09320](https://arxiv.org/abs/1603.09320))
  The algorithm Chroma (and most modern vector stores) actually use under the hood.
- **Pinecone, "What is a vector database?"** — [pinecone.io/learn/vector-database](https://www.pinecone.io/learn/vector-database/)
  A vendor-agnostic explainer; a good companion read to the concepts doc.

## Embeddings

- **Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks** — Reimers & Gurevych, 2019 ([arXiv 1908.10084](https://arxiv.org/abs/1908.10084))
  The paper that introduced the training approach behind `sentence-transformers`.
- **`sentence-transformers` documentation** — [sbert.net](https://www.sbert.net/)
  Practical guide to choosing and using embedding models, including the model card for `all-MiniLM-L6-v2`.
- **MTEB Leaderboard** — [huggingface.co/spaces/mteb/leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
  The standard benchmark for comparing embedding models. Useful when evaluating swaps.

## Chunking

- **Lost in the Middle: How Language Models Use Long Contexts** — Liu et al., 2023 ([arXiv 2307.03172](https://arxiv.org/abs/2307.03172))
  Why dumping everything into a long context is not the same as good retrieval.
- **LangChain — Text Splitters guide** — [python.langchain.com/docs/concepts/text_splitters](https://python.langchain.com/docs/concepts/text_splitters/)
  A walkthrough of common chunking strategies (fixed, recursive, semantic, structure-aware) with examples.
- **LlamaIndex — Chunking strategies** — [docs.llamaindex.ai](https://docs.llamaindex.ai/en/stable/optimizing/production_rag/#decoupling-chunks-used-for-retrieval-vs-chunks-used-for-synthesis)
  Discusses decoupling retrieval chunks from generation chunks (a Phase-3+ refinement we do not do).

## RAG end-to-end

- **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks** — Lewis et al., 2020 ([arXiv 2005.11401](https://arxiv.org/abs/2005.11401))
  The original RAG paper. Worth reading for the framing even though the architecture has evolved.
- **Anthropic, Building effective agents (RAG section)** — [anthropic.com/research/building-effective-agents](https://www.anthropic.com/research/building-effective-agents)
  Production patterns for RAG and where it fits in larger systems.

## Engineering practice

- **Pydantic Settings docs** — [docs.pydantic.dev/latest/concepts/pydantic_settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
  Reference for the `BaseSettings` we use in `app/config.py`.
- **Architecture Decision Records (ADRs) by Michael Nygard** — [cognitect.com/blog/2011/11/15/documenting-architecture-decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
  The original short blog post that introduced the ADR format we use under `docs/00-design/adrs/`.

## Optional but worth a skim

- **Twelve-Factor App** — [12factor.net](https://12factor.net/)
  The "config" factor (env-driven configuration) is the principle behind `app/config.py`.
- **`pdfplumber` README** — [github.com/jsvine/pdfplumber](https://github.com/jsvine/pdfplumber)
  Useful if you want to do anything beyond plain text extraction (tables, layout).

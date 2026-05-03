# ADR 0003 — Use sentence-transformers `all-MiniLM-L6-v2` for embeddings

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

Every chunk and every query has to be embedded into a dense vector.
The choice influences:

- ingestion speed (we re-embed on every ingest)
- retrieval quality (better embeddings → better top-K)
- runtime cost (paid embedding APIs add per-call cost)
- portability (running offline, in CI, in Docker)

## Decision

Use **`sentence-transformers/all-MiniLM-L6-v2`** as the default
embedding model. It is loaded locally via the
[`sentence-transformers`](https://www.sbert.net/) library. The model
name is configurable via the `EMBED_MODEL` setting; tests inject a
deterministic fake embedder so they do not need to download the
model.

## Consequences

**Positive**:

- Tiny: ~80 MB on disk and a few hundred MB of RAM. CPU-only inference
  is fast (sub-100 ms per chunk on a typical laptop).
- 384-dimensional output, which keeps ChromaDB indices small.
- Solid quality on general English text and a strong baseline on the
  MTEB leaderboard.
- Free, open weights, runs offline.

**Negative / accepted trade-offs**:

- Quality is below larger models like `bge-large-en` or
  `text-embedding-3-large`. For technical engineering docs the gap
  is usually small but real.
- English-centric. Multilingual content would need a different model
  (`paraphrase-multilingual-MiniLM-L12-v2`).
- 256-token input limit. Chunks longer than this are truncated, which
  is fine because our chunker stays well under that.

## Alternatives considered

### `bge-small-en-v1.5` / `bge-base-en-v1.5`

- *Pros:* better MTEB scores than MiniLM, still small.
- *Cons:* slightly heavier. A reasonable swap; we leave it as an
  exercise in `docs/01-ingestion/README.md` ("re-ingest with bge-small
  and compare").

### OpenAI `text-embedding-3-small`

- *Pros:* very strong quality, only 1536 dims, predictable latency.
- *Cons:* paid (per-token). Conflicts with NFR-4.

### Cohere embeddings

- *Pros:* good quality, has a free tier.
- *Cons:* network dependency, account required, conflicts with the
  goal of running fully locally.

### Instructor models / E5

- *Pros:* instruction-tuned embeddings can boost retrieval.
- *Cons:* more setup (instruction prefixes), not worth it at our
  scale.

## When we would revisit

- the corpus expands meaningfully and retrieval quality plateaus
- we need multilingual support
- we observe that retrieval ranks mediocre chunks above clearly
  better ones in evaluation runs

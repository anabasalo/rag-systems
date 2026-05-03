# ADR 0001 — Use ChromaDB as the vector store

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

The system needs a vector database to store chunk embeddings and run
top-K similarity search. Requirements relevant to this decision:

- runs locally with no paid services
- persists to disk between restarts
- supports metadata filtering (collections + per-chunk metadata)
- has a Python client and modest setup overhead
- can comfortably hold a few thousand chunks (the project corpus)

## Decision

Use **[ChromaDB](https://www.trychroma.com/)** in **embedded
(in-process) mode**, with the persistent store at `./data/chroma/`.

The ChromaDB client is wrapped behind `app/db/vector_store.py`. No
other module imports the `chromadb` package directly. This keeps the
choice swappable.

## Consequences

**Positive**:

- Zero infrastructure: ChromaDB runs in the same Python process as
  FastAPI. No separate service to start.
- Persistence is a single directory we mount as a Docker volume.
- The Python API exposes both vector search and metadata `where`
  filters, which is exactly what our scoping model needs (see
  ADR 0005).
- Active OSS project with good docs.

**Negative / accepted trade-offs**:

- Embedded mode is single-process. If we ever needed concurrent
  writers from multiple services, we would have to switch to the
  ChromaDB server mode (or another DB).
- Performance and recall quality are competitive but not class-leading
  for very large corpora. For our scope (under ~10k chunks) this is
  fine.
- The on-disk format is internal to Chroma; backing up means copying
  the directory.

## Alternatives considered

### FAISS

- *Pros:* fast, mature, no service.
- *Cons:* index-only — no built-in metadata store. We would have to
  bolt on SQLite for metadata. More moving parts than Chroma.

### Pinecone

- *Pros:* managed, fast, scales effortlessly.
- *Cons:* paid (free tier exists but is usage-limited and requires an
  account), and adds a network dependency. Conflicts with NFR-4
  (zero cost) and NFR-5 (works from a clean clone with just Docker).

### Weaviate

- *Pros:* powerful (vector + keyword + GraphQL), self-hostable.
- *Cons:* heavier to operate (extra container, schema setup). Useful
  if we wanted hybrid retrieval out of the box, but we will build
  hybrid retrieval ourselves in Phase 3 to learn the mechanics.

### pgvector (Postgres extension)

- *Pros:* uses a database many engineers already know.
- *Cons:* requires Postgres, which is another service. Setup cost
  exceeds the value at this scale.

### Qdrant

- *Pros:* fast, good metadata filtering, self-hostable.
- *Cons:* very close to Chroma in capabilities, but adds a separate
  service container. Chroma's embedded mode wins on simplicity.

## When we would revisit

- corpus grows past ~100k chunks
- we need multiple writer processes
- we need cross-collection search with shared filters

# ADR 0005 — Two-layer scoping: collections + metadata filters

- **Status:** Accepted
- **Date:** 2026-05-03

## Context

The system is designed around a real use case: a user uploads many
documents and later wants to ask a question over a subset of them.
Concrete scenario: 30 documents are ingested; the user wants the
answer to draw only from 3 specific files.

There are several ways to model this in a vector store:

1. one big index, no scoping (impractical — every query searches
   everything)
2. one collection per document (forces clients to know all
   documents and aggregate)
3. namespaces / partitions (some vendors expose this)
4. **collections + metadata filters** (collections as logical
   knowledge bases, metadata for finer scoping)

## Decision

Use a **two-layer scoping model**:

- **Layer 1 — Collections** are logical knowledge bases. Examples:
  `kubernetes-docs`, `aws-docs`, `internal-runbooks`. A query targets
  exactly one collection. There is no implicit "search all
  collections".
- **Layer 2 — Metadata filters** narrow within a collection. Every
  chunk carries `doc_id`, `doc_name`, `tags`, `uploaded_at`,
  `source_type`. A query may pass `doc_filter` to restrict retrieval
  by `doc_name` or `tags`.

This is implemented natively in ChromaDB:

```python
collection.query(
    query_embeddings=[embedding],
    n_results=k,
    where={"doc_name": {"$in": ["scaling.md", "hpa.md"]}},
)
```

## Consequences

**Positive**:

- Matches how users actually think about their docs ("ask about
  Kubernetes" → collection; "only the HPA pages" → filter).
- Clean isolation between unrelated corpora (a chunk in `aws-docs`
  cannot leak into a `kubernetes-docs` query).
- No client-side aggregation: the server enforces scoping.
- Filters compose with the chosen retrieval strategy. Both
  `basic` (vector) and `improved` (BM25 + vector + MMR) honor the
  same `where` clause.

**Negative / accepted trade-offs**:

- A user has to know which collection their docs are in. We mitigate
  with `GET /collections` and `GET /collections/{name}/docs`.
- Cross-collection search is not supported by design. If someone
  needed it, they would have to call `/query` per collection and
  fuse the results client-side.

## Alternatives considered

### Single index with everything

- *Pros:* simplest possible model.
- *Cons:* no isolation, no efficient scoping. Every user's docs
  pollute every other user's retrieval.

### One collection per document

- *Pros:* perfect isolation per document.
- *Cons:* explodes the number of collections and forces clients to
  fan-out. Defeats the point of a vector DB index.

### Namespaces (vendor-specific)

- *Pros:* clean separation in vendors that support them (e.g.,
  Pinecone).
- *Cons:* not first-class in ChromaDB. Collections are the closest
  primitive.

### Tag-only scoping

- *Pros:* minimal: one global index plus tags.
- *Cons:* loses the "logical knowledge base" abstraction. Two users
  with overlapping tag names would collide.

## When we would revisit

- we add multi-tenancy and need per-tenant isolation that survives
  a misconfigured tag
- we want global cross-collection search as a first-class feature
- we move to a vector DB whose primitives suggest a different mapping

# Phase 1 — Concepts

Plain-language explanations of the ideas this phase relies on. Read
this before the walkthrough if any of these terms are unfamiliar.

## What is an embedding?

An **embedding** is a fixed-length vector of floating-point numbers
that represents a piece of text in a way that captures its meaning.
The output of `embed("the cat sat on the mat")` is a list of, say, 384
numbers. Two pieces of text with similar meanings produce vectors
that are close together in that 384-dimensional space; two unrelated
pieces of text produce vectors far apart.

The model that produces embeddings is trained so that this geometric
property holds. We don't engineer it; we use a pretrained model
(`all-MiniLM-L6-v2`) and trust the training.

The crucial mental shift: **once text is an embedding, similarity
becomes geometry**. We can ask "what's the closest chunk to this
query?" with a fast nearest-neighbor search instead of any
keyword-based heuristic.

## What is a chunk?

LLMs and embedding models have a fixed input size (a few hundred to a
few thousand tokens). A 50-page PDF will not fit. So we split the
document into **chunks**: a few paragraphs each, each independently
embeddable.

The unit of retrieval is the chunk, not the document. When you ask a
question, the system returns the *chunks* most relevant to your
query. The LLM then produces an answer from those chunks plus your
question.

Why this matters: chunk size is a *retrieval* decision, not a UI
decision. Smaller chunks → finer-grained matches but more fragmented
context. Larger chunks → more coherent context but coarser matches
and faster context-window exhaustion. ADR 0004 explains the default.

## What is overlap?

Suppose a chunk ends mid-sentence at "Kubernetes scales pods using"
and the next chunk starts with "the Horizontal Pod Autoscaler". A
question about "Horizontal Pod Autoscaler" will match the second
chunk and miss the connection to scaling.

**Overlap** means consecutive chunks share their boundary text. With
2000-character chunks and 200-character overlap, chunk N+1 starts at
position `(2000 - 200)` of where chunk N started. This way, *facts
that live near a boundary are reachable from either chunk*.

The cost is duplicate text in the index: with 10% overlap, the
collection is roughly 10% larger than the source corpus.

## What is a vector store / vector database?

A **vector store** is a database optimized for one query type:
"given a vector `q`, return the K stored vectors closest to it,
along with the documents and metadata they came from".

Internally, vector stores use approximate-nearest-neighbor (ANN)
indexes — typically HNSW (Hierarchical Navigable Small World) — that
trade a tiny bit of recall for query latency that stays roughly
constant as the collection grows. ChromaDB uses HNSW under the hood.

A vector store is *not* a relational database. There are no joins,
no transactions across rows, no foreign keys. It does store
metadata alongside each vector and supports filtering on it (the
`where` clause in this project), which is what makes scoping by
`doc_name` and `tags` possible.

## What is cosine similarity?

Two vectors `a` and `b` have **cosine similarity**:

```
cos(a, b) = (a · b) / (|a| * |b|)
```

It is the cosine of the angle between them. The value ranges from
`-1` (opposite directions) through `0` (orthogonal) to `+1`
(identical direction). For typical embeddings, similar texts produce
cosine values around `+0.4` to `+0.9`; unrelated texts cluster near
`0`.

ChromaDB returns *distance*, not similarity, defined as
`1 - cosine_similarity`. Our `VectorStore.query` converts back so
the rest of the project works in similarity terms (higher = better).

## Collections vs. metadata filters

A **collection** is a named, isolated index — like a separate table
in a database. Two collections never see each other's vectors, even
if you used the same embedding model.

**Metadata filters** narrow within a collection. We attach
`{doc_id, doc_name, chunk_index, tags, uploaded_at, source_type}` to
every chunk, and `query(..., where={...})` only considers chunks
whose metadata matches.

Together they give us two-axis scoping: one collection per logical
knowledge base, plus filters for "only these specific docs". See
ADR 0005.

## What metadata does for you

It looks bureaucratic, but each field earns its keep:

- **`doc_id`** — a UUID minted at ingestion time. Lets us answer "did
  this answer come from a particular ingestion run?" and lets re-
  ingestion replace old chunks cleanly.
- **`doc_name`** — what the user sees in citations. Also the natural
  granularity for filters.
- **`chunk_index`** — the ordinal position of the chunk in the source
  document. Useful when displaying citations in document order or
  when a user wants to see "the next chunk after this one".
- **`tags`** — user-supplied free-form labels. Stored as a CSV string
  because ChromaDB metadata values must be primitive.
- **`uploaded_at`** — ISO timestamp. Used by `list_docs` to show when
  a doc was last seen and as a tiebreaker in re-ingest.
- **`source_type`** — `"pdf"`, `"markdown"`, or `"text"`. Useful for
  evaluation (does retrieval favor one source type?) and for future
  features like format-aware chunking.

## What "production-shaped" means in this phase

Three things were chosen deliberately to make the code feel like
real software, not a notebook script:

1. **Dependency injection.** The ingestion function does not
   construct an embedder or a vector store; it accepts them. Tests
   substitute fakes. Production wires up the real ones in the
   script (and in Phase 2's API factory).
2. **A single seam for persistence.** ChromaDB is wrapped behind one
   class. If we ever swap to Qdrant or pgvector, exactly one file
   changes.
3. **Idempotent re-ingest.** Re-uploading the same `doc_name`
   replaces its chunks. Without this, a re-ingest doubles the
   collection and corrupts retrieval. The corresponding test
   pinned this behavior the moment the code was written.

These are habits, not heroics. They are the difference between code
you can keep and code you have to rewrite later.

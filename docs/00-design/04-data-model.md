# Data model

This document describes every persistent entity in the system, where it
lives, and how it is identified.

## Overview

Three kinds of state:

1. **Vector data** — chunks of documents and their embeddings, stored
   in ChromaDB at `data/chroma/`.
2. **Operational logs** — one JSON line per query at
   `logs/queries.jsonl`.
3. **Evaluation set** — a hand-curated JSON file of Q&A pairs at
   `data/eval/qa_pairs.json`.

There is no relational database. ChromaDB stores chunks, embeddings,
and metadata together; everything else is flat files.

## Collections

A **collection** is a logical, isolated index in ChromaDB. Example
collections: `kubernetes-docs`, `aws-docs`, `internal-runbooks`. Each
collection has its own embedding space (in practice all collections
use the same embedding model, but they are queried independently).

Naming rules:

- lower-case ASCII, hyphens, digits
- 3–63 characters
- must be unique within the ChromaDB instance

Collections are created lazily on first ingest. Deleting a collection
deletes every chunk in it.

## Chunk schema

Every chunk stored in ChromaDB has four pieces of state:

| Field | Type | Owner | Description |
| --- | --- | --- | --- |
| `id` | string (UUID) | Chroma | unique chunk identifier |
| `document` | string | Chroma | the chunk text |
| `embedding` | float vector | Chroma | dense embedding (dim = model output) |
| `metadata` | dict | app | metadata fields (see below) |

### Metadata fields

These fields are written by `core/ingestion.py` for every chunk and
are queryable via Chroma `where` filters.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `doc_id` | string (UUID) | yes | stable id for the source document |
| `doc_name` | string | yes | original filename, e.g. `kubernetes_scaling.md` |
| `chunk_index` | int | yes | 0-based index of the chunk within the doc |
| `tags` | string (CSV) | no | comma-separated user-supplied tags |
| `uploaded_at` | string (ISO 8601) | yes | timestamp of ingestion |
| `source_type` | string | yes | one of `pdf`, `markdown`, `text` |

> Note on `tags`: ChromaDB metadata values must be primitive types
> (string, number, bool). We store tags as a comma-separated string
> and parse on read. Filtering by tag uses a substring `where`
> filter.

## Document identity

A document is identified by the pair `(collection, doc_name)`. When
the same `doc_name` is re-ingested into the same collection, the
existing chunks for that document are deleted before the new ones
are inserted. This keeps re-ingestion idempotent and prevents
duplicate chunks.

Each ingestion run also assigns a fresh `doc_id` to the new version
of the document; old chunks (which had the previous `doc_id`) are
removed.

## Query log entry schema

`logs/queries.jsonl` is append-only. One JSON object per line. Fields:

```json
{
  "ts": "2026-05-03T16:42:11.832Z",
  "endpoint": "/query",
  "question": "How does Kubernetes handle pod scaling?",
  "collection": "kubernetes-docs",
  "doc_filter": null,
  "strategy": "basic",
  "k": 5,
  "retrieved_chunk_ids": ["a1b2...", "c3d4..."],
  "answer_preview": "Kubernetes scales pods using the Horizontal...",
  "latency_ms": 1240,
  "tokens": {
    "prompt": 812,
    "completion": 144
  },
  "status": "ok"
}
```

Notes:

- `answer_preview` is the first ~200 characters of the answer, not
  the full text. The full answer is not retained in logs.
- `tokens` is included when the LLM provider returns it; otherwise
  `null`.
- `status` is `ok`, `empty_context`, or `llm_error`.
- We do not log retrieved chunk *text* in the JSONL log — only
  chunk IDs. If you need to inspect the chunks for a logged query,
  re-run the retrieval against the persisted ChromaDB.

## Evaluation set schema

`data/eval/qa_pairs.json` is a hand-curated array of objects:

```json
[
  {
    "id": "k8s-001",
    "collection": "kubernetes-docs",
    "question": "What does the Horizontal Pod Autoscaler scale?",
    "ground_truth": "It scales the number of pod replicas in a workload based on observed CPU utilization or other metrics.",
    "answerable": true,
    "tags": ["scaling", "hpa"]
  },
  {
    "id": "k8s-unanswerable-001",
    "collection": "kubernetes-docs",
    "question": "What is the price of GitHub Enterprise?",
    "ground_truth": null,
    "answerable": false,
    "tags": ["unanswerable"]
  }
]
```

The `answerable: false` entries are critical: they verify that the
system declines to answer when the corpus does not support an answer.

## Storage layout on disk

```
data/
├── raw/                  # original uploaded source files (kept for re-ingest)
│   ├── kubernetes/
│   │   ├── scaling.md
│   │   └── hpa.md
│   └── aws/
│       └── well-architected.pdf
├── chroma/               # ChromaDB persistent files (DO NOT EDIT BY HAND)
│   └── ...
└── eval/
    └── qa_pairs.json     # hand-curated Q&A pairs

logs/
└── queries.jsonl         # append-only structured query log
```

## What is *not* in the data model

- no `User` entity (no auth)
- no `Tenant` / `Organization` (collections are the only multi-tenancy)
- no document version history (re-ingest replaces)
- no cached LLM responses (every query hits Groq)

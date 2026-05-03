# Phase 1 — Document Ingestion

This is the first executable phase. There is no HTTP API yet; that is
Phase 2. Here we build the pipeline that turns a file on disk into
searchable chunks in a vector store.

## Learning goals

After this phase you can:

- Explain what a chunk is, what an embedding is, and why both are needed.
- Walk through the ingestion pipeline end to end (parse → chunk → embed
  → store) and name the responsibility of each step.
- Read the chunk metadata schema and recognize what each field is for
  (`doc_id`, `doc_name`, `chunk_index`, `tags`, `uploaded_at`,
  `source_type`).
- Choose chunk size and overlap deliberately rather than by default.
- Recognize the difference between a *vector store* and a relational
  database, and explain why it matters for retrieval.

If any of these terms are new, read [`concepts.md`](concepts.md) first.

## What was built

| File | Role |
| --- | --- |
| [`app/config.py`](../../app/config.py) | Typed settings loaded from `.env` (`Settings` + `get_settings`) |
| [`app/core/embedders.py`](../../app/core/embedders.py) | `Embedder` protocol + `SentenceTransformerEmbedder` (lazy load) |
| [`app/core/ingestion.py`](../../app/core/ingestion.py) | `chunk_text`, `ingest`, `IngestionResult`, `IngestionError` |
| [`app/db/vector_store.py`](../../app/db/vector_store.py) | The single ChromaDB wrapper for the whole project |
| [`app/scripts/ingest_demo.py`](../../app/scripts/ingest_demo.py) | CLI demo script for end-to-end verification |
| [`tests/conftest.py`](../../tests/conftest.py) | `tmp_chroma_dir`, `fake_embedder`, `make_doc` fixtures |
| [`tests/test_ingestion.py`](../../tests/test_ingestion.py) | 17 unit tests for chunking, ingestion, isolation, idempotence |

The architecture invariant is enforced: only `app/db/vector_store.py`
imports `chromadb`, and only `app/core/ingestion.py` knows the chunk
metadata schema. Everything above sees value objects (`IngestionResult`,
`DocSummary`, `RetrievedChunk`).

## Walkthrough

### 1. Settings — `app/config.py`

A single Pydantic `BaseSettings` class is the source of truth for
configuration. Defaults live in code; overrides come from environment
variables (and from `.env` for local runs). `get_settings()` is
LRU-cached so we have one Settings instance per process.

Key fields used in this phase: `embed_model`, `chroma_persist_dir`,
`chunk_size`, `chunk_overlap`.

### 2. Embeddings — `app/core/embedders.py`

`Embedder` is a `Protocol` (structural type) with one method:

```python
def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
```

The real implementation, `SentenceTransformerEmbedder`, lazy-loads the
model on first call. Tests inject a fake embedder so the suite is fast
and offline; the production code path never knows the difference.

This is the dependency-injection seam that makes the rest of the
phase testable.

### 3. Chunking — `chunk_text` in `app/core/ingestion.py`

Fixed-size with overlap. Within ±10% of the target size we look for a
clean boundary, in order of preference: paragraph break (`\n\n`),
sentence end (`. `), newline (`\n`). If none is found in the window,
we fall back to a hard character split. This keeps the implementation
small while producing readable chunks on well-formatted documents.

Key invariants the tests guarantee:

- empty / whitespace input → `[]`
- input shorter than the target size → exactly one chunk
- when no natural boundary exists, adjacent chunks share an `overlap`-
  length suffix/prefix (the test
  `test_chunk_text_chunks_have_overlap_when_no_natural_boundary` pins
  this)
- when a paragraph break exists near the target size, the split snaps
  to it

See ADR 0004 for the alternatives we considered and rejected.

### 4. Vector store — `app/db/vector_store.py`

A thin wrapper exposing only the operations the rest of the project
needs:

- `get_or_create_collection`, `delete_collection`, `collection_exists`
- `list_collections`, `list_docs`
- `add_chunks`, `delete_doc`
- `query`

Two design choices worth noting:

1. **Cosine, not L2.** Every collection is created with
   `metadata={"hnsw:space": "cosine"}`. The `query` method then
   computes similarity as `1 - distance`. This matches every formula
   in the design docs and the eval phase.
2. **Value objects, not Chroma objects.** `query` returns a list of
   `RetrievedChunk` dataclasses, never raw Chroma rows. Future phases
   build on these shapes; if Chroma changes API, only this file
   changes.

### 5. Ingestion — `ingest()` in `app/core/ingestion.py`

The full sequence:

1. validate the file exists and the extension is supported
2. parse to text (`pdfplumber` for PDF; `read_text` for MD/TXT)
3. chunk with the configured size and overlap
4. mint a fresh `doc_id` (UUID4)
5. assemble metadata for every chunk
6. **delete any existing chunks with the same `doc_name`** — this is
   what makes re-ingest idempotent (FR-1.4)
7. embed all chunks in one call
8. write to the vector store
9. return an `IngestionResult`

### 6. Demo script — `app/scripts/ingest_demo.py`

A small CLI that wires `Settings` + `SentenceTransformerEmbedder` +
`VectorStore` + `ingest()` together. After ingesting it runs a tiny
top-3 query against the collection so you can see the pipeline
working without writing any extra code.

## How to run it

### One-time setup

```bash
cd /home/albasalo/projects/rag-systems
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

(`requirements-dev.txt` includes the runtime deps.)

### Run the unit tests

```bash
source .venv/bin/activate
ruff check app tests
ruff format --check app tests
pytest -v
```

Expected: 17 passed, no lint errors.

### Run the ingest demo

The first run downloads the embedding model (~80 MB).

```bash
source .venv/bin/activate
HF_HOME=$(pwd)/.cache/huggingface python -m app.scripts.ingest_demo
```

`HF_HOME` is optional; it just keeps the model cache inside the
project directory instead of `~/.cache/huggingface`.

You should see something like:

```
[ingest] data/raw/sample.md -> collection 'demo' (tags=-)
  doc_id          = ...
  doc_name        = sample.md
  source_type     = markdown
  chunks_written  = 2
  uploaded_at     = 2026-...

[smoke] top-3 for query: 'scaling and capacity'
  score=+0.460  sample.md#chunk1: ...
  score=+0.447  sample.md#chunk0: ...
```

### Reset state

```bash
rm -rf data/chroma/*
```

That clears every collection. The original document file at
`data/raw/sample.md` is left alone.

## Exercises

These are intentionally small. Each one should take under 15 minutes.

1. **Tune chunking.** Change `CHUNK_SIZE` to `512` in `.env` and run
   the demo again. How many chunks do you get for `sample.md` now?
   Then try `4000`. Discuss the trade-off you observed in two
   sentences.

2. **Swap the embedder.** Set `EMBED_MODEL=BAAI/bge-small-en-v1.5` in
   `.env`, clear `data/chroma/`, and re-run the demo. Compare the top
   scores on the smoke query against the default.

3. **Add a doc by hand.** Drop another `.md` or `.txt` file under
   `data/raw/` and ingest it with
   `python -m app.scripts.ingest_demo --file data/raw/your.md
   --collection demo`. Confirm `list_docs` reports both files.

4. **Verify idempotence.** Run the demo twice in a row without
   clearing `data/chroma/`. Confirm the chunk count for `sample.md`
   does not double. (Look at the relevant test if you want to know
   why.)

## What's next

In Phase 2 we wrap this pipeline in a FastAPI app, add the LLM call
that turns retrieved chunks into a grounded answer, and start
returning citations. Same `core/` and `db/` modules, just an HTTP
layer on top.

## Further reading

- [`concepts.md`](concepts.md) — embeddings, vector stores, chunking
  explained
- [`alternatives.md`](alternatives.md) — what else we could have used
- [`references.md`](references.md) — papers, official docs, blog
  posts
- ADRs: [`0001`](../00-design/adrs/0001-vector-db-chromadb.md),
  [`0003`](../00-design/adrs/0003-embedding-model.md),
  [`0004`](../00-design/adrs/0004-chunking-strategy.md)

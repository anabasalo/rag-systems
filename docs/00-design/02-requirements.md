# Requirements

This document is the contract the rest of the project implements against.
Items are intentionally small and testable.

## Functional requirements

### FR-1: Document ingestion

- **FR-1.1** The system accepts PDF, Markdown, and plain-text uploads.
- **FR-1.2** Each upload is parsed into text, split into overlapping
  chunks, embedded, and stored in a vector database.
- **FR-1.3** Every chunk carries metadata at minimum: `doc_id`,
  `doc_name`, `tags` (optional list of strings), and `uploaded_at`
  (ISO 8601 timestamp).
- **FR-1.4** Re-ingesting a document with the same `doc_name` into the
  same collection deletes the previous chunks for that document before
  inserting the new ones.

### FR-2: Collections and scoping

- **FR-2.1** Documents are organized into named **collections** (logical
  knowledge bases). Examples: `kubernetes-docs`, `aws-docs`.
- **FR-2.2** A collection is created on first ingest and persists across
  restarts.
- **FR-2.3** Every query targets exactly one collection. There is no
  implicit "all collections" query.
- **FR-2.4** A query may optionally include a `doc_filter` that
  restricts retrieval to a subset of documents within the collection by
  `doc_name` or `tags`.
- **FR-2.5** The system exposes endpoints to list collections, list the
  documents in a collection, and delete either a single document or an
  entire collection.

### FR-3: Query and generation

- **FR-3.1** Given a question and a collection, the system retrieves
  the top-K most relevant chunks and asks an LLM to answer using only
  those chunks.
- **FR-3.2** The response always contains: the answer string, the list
  of source chunks used (text + `doc_name` + similarity score), the
  collection name, and the latency in milliseconds.
- **FR-3.3** If retrieval returns no chunks above a similarity floor,
  the system returns an explicit "I cannot answer from the provided
  documents" message rather than calling the LLM with empty context.

### FR-4: Retrieval comparison

- **FR-4.1** The system supports at least two retrieval strategies:
  - `basic`: pure dense (vector) cosine similarity, top-K
  - `improved`: hybrid BM25 + vector with MMR re-ranking
- **FR-4.2** A `/compare` endpoint runs both strategies on the same
  question and returns both answers and both source lists.

### FR-5: Evaluation

- **FR-5.1** The system can score an answer with at least:
  faithfulness, answer relevancy, and context precision.
- **FR-5.2** An evaluation run can be executed against a JSON file of
  Q&A pairs and produces a summary report comparing strategies.
- **FR-5.3** The eval set includes at least one unanswerable question
  to verify the "I don't know" behavior.

### FR-6: Observability

- **FR-6.1** Every query is logged as a structured JSON line with at
  minimum: timestamp, question, collection, retrieval strategy, list
  of retrieved chunk IDs, latency, and (if available) token count.
- **FR-6.2** The system exposes `GET /health` returning service status
  and the number of collections.
- **FR-6.3** The system exposes `GET /logs?limit=N` returning the last
  N query log entries.

## Non-functional requirements

### NFR-1: Performance

- **NFR-1.1** End-to-end `/query` latency target: under 3 seconds on a
  developer laptop, when the corpus is under 1,000 chunks.
- **NFR-1.2** Embeddings are computed once at ingestion time and reused
  for all subsequent queries.

### NFR-2: Reliability

- **NFR-2.1** The system handles empty results, unknown collections,
  malformed uploads, and LLM failures with clear HTTP error codes
  (`404`, `422`, `502`) rather than 500s.
- **NFR-2.2** A failure of the LLM call must not corrupt the vector
  store.

### NFR-3: Maintainability

- **NFR-3.1** The codebase is layered: HTTP handlers under `app/api/`,
  business logic under `app/core/`, persistence under `app/db/`. The
  vector store is touched only from `app/db/`.
- **NFR-3.2** Configuration is centralized in `app/config.py` (Pydantic
  Settings) and loaded from environment variables.
- **NFR-3.3** Lint passes (`ruff`) and the test suite is green in CI on
  every push.

### NFR-4: Cost

- **NFR-4.1** The system runs at zero monetary cost on free tiers and
  open-source components. No paid APIs are required.

### NFR-5: Reproducibility

- **NFR-5.1** A single `docker compose up` (with a populated `.env`)
  brings up a working service from a fresh clone.
- **NFR-5.2** ChromaDB and query logs are persisted via mounted volumes
  so state survives container restarts.

## Non-requirements (explicitly out of scope)

- authentication, authorization, multi-user accounts
- a production frontend (a minimal Streamlit page is optional)
- token streaming
- horizontal scaling
- multi-version document history
- fine-tuning of any model
- monitoring dashboards (Prometheus, Grafana, OpenTelemetry)

## Acceptance test (Phase 5 milestone)

A reviewer should be able to, from a clean clone:

1. populate `.env` from `.env.example`,
2. run `docker compose up`,
3. ingest two documents via `curl`,
4. ask a grounded question, an unanswerable question, and a comparison
   query, and observe the documented response shapes,
5. read the last queries via `/logs`.

If all five steps succeed, the project meets its requirements.

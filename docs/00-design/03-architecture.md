# Architecture

## High-level diagram

```mermaid
flowchart TD
    subgraph ingestion [Ingestion Pipeline]
        A["Upload File + collection + tags"] --> B[Parse PDF/MD/TXT]
        B --> C["Chunk (fixed-size + overlap)"]
        C --> D[Embed with sentence-transformers]
        D --> E[("ChromaDB - collection per knowledge base")]
    end

    subgraph query [Query Pipeline]
        F["Question + collection + doc_filter"] --> G[Embed Question]
        G --> H{Retrieval Strategy}
        H -->|basic| I["Top-K cosine + metadata filter"]
        H -->|improved| J["Hybrid BM25 + Vector + MMR + filter"]
        I --> K[Assemble Context + Prompt]
        J --> K
        K --> L[Groq LLM]
        L --> M["Answer + Citations"]
    end

    subgraph evalSection [Evaluation]
        N[Query + Answer + Context] --> O[RAGAS Scorer]
        O --> P["Faithfulness, Relevance, Context Precision"]
    end

    subgraph obs [Observability]
        Q[queries.jsonl] --> R["latency, tokens, strategy, collection"]
    end

    M --> N
    M --> Q
    E --> I
    E --> J
```

## Layered code structure

The project is intentionally three layers, with strict direction of
dependency: `api/ -> core/ -> db/`. Layers above never import from
layers below the wrong way around.

```
app/
├── api/             # HTTP layer (FastAPI routers, request/response)
├── core/            # Business logic (no FastAPI, no Chroma imports)
├── db/              # Persistence (the only place ChromaDB is touched)
├── observability/   # Logging adapters
├── schemas.py       # Pydantic models shared by api/ and core/
├── config.py        # Pydantic Settings (env-driven configuration)
└── main.py          # FastAPI app factory and wiring
```

Why these layers:

- **`api/`** is thin. It validates input with Pydantic, calls into
  `core/`, and serializes the result. Swapping FastAPI for another
  framework should not require changes outside `api/`.
- **`core/`** contains the actual RAG pipeline (ingestion, retrieval,
  generation, evaluation). It is testable without running an HTTP
  server and without a real ChromaDB or LLM (both are passed in via
  small interfaces).
- **`db/`** owns the ChromaDB client and is the only module that
  speaks Chroma's API. Replacing the vector store later means changing
  this directory only.

## Component responsibilities

| Component | File(s) | Responsibility |
| --- | --- | --- |
| Ingestion | `core/ingestion.py` | parse → chunk → embed → write to `db/` |
| Vector store | `db/vector_store.py` | manage collections, add/query/delete chunks |
| Retrieval | `core/retrieval.py` | implement `basic` and `improved` strategies on top of `db/` |
| Generation | `core/generation.py` | assemble prompt, call Groq, return answer |
| Evaluation | `core/evaluation.py` | wrap RAGAS, run a Q&A set, summarize scores |
| Observability | `observability/logger.py` | append-only JSONL writer + reader |
| Configuration | `config.py` | typed settings loaded from env |
| API | `api/*.py` | HTTP endpoints, error mapping |

## Request lifecycle: `POST /query`

```mermaid
sequenceDiagram
    participant U as Client
    participant A as api/query.py
    participant C as core/retrieval.py
    participant DB as db/vector_store.py
    participant G as core/generation.py
    participant L as Groq LLM
    participant O as observability/logger.py

    U->>A: POST /query (question, collection, doc_filter, strategy)
    A->>A: validate with Pydantic (schemas.py)
    A->>C: retrieve(collection, question, k, where, strategy)
    C->>DB: query(collection, embedding, k, where)
    DB-->>C: top-K chunks + scores
    alt no chunks above floor
        C-->>A: empty result
        A-->>U: 200 {answer: "I cannot answer...", sources: []}
    else chunks found
        C->>G: generate(question, chunks)
        G->>L: chat completion (prompt with citations)
        L-->>G: answer text
        G-->>C: answer
        C-->>A: answer + chunks + latency
        A->>O: log_query(...)
        A-->>U: 200 {answer, sources, latency_ms}
    end
```

## Cross-cutting concerns

### Configuration

All configuration lives in `app/config.py` as a Pydantic `Settings`
class loaded from environment variables (with `.env` support via
`python-dotenv`). Anything that varies by environment — model names,
ChromaDB path, top-K, similarity floor, log path — is a setting.
Hardcoded values in code are a smell.

### Error handling

A small set of custom exceptions in `app/core/exceptions.py`
(`CollectionNotFound`, `LLMUnavailable`, `IngestionError`) is mapped
to HTTP status codes by FastAPI exception handlers in `app/main.py`.
Layers below `api/` never raise `HTTPException` directly.

### Logging

Two logs:

1. **Query log**: append-only JSONL at `logs/queries.jsonl`. Written
   for every successful query. Used by `GET /logs`.
2. **Application log**: standard `logging` module to stdout, captured
   by Docker. Used for diagnostics, not queryable from the API.

### Persistence

- **ChromaDB** under `data/chroma/`, persistent between runs.
- **Query log** under `logs/queries.jsonl`, append-only.
- **Eval Q&A pairs** under `data/eval/qa_pairs.json`, hand-curated.

In Docker, both `data/` and `logs/` are mounted as volumes.

## Failure modes considered

| Failure | Detection | Behavior |
| --- | --- | --- |
| Unknown collection | `db/` returns `None` for `get_collection` | `404 CollectionNotFound` |
| Empty retrieval | `core/retrieval` returns `[]` | `200` with safe message, no LLM call |
| LLM 5xx / timeout | exception from Groq client | `502 LLMUnavailable` after one retry |
| Malformed upload | parser raises | `422 IngestionError` |
| Disk full / Chroma write fail | exception from `db/` | `500`, error logged |

## Why this shape (and not microservices)

For a corpus of thousands of chunks and a single user, splitting
ingestion, retrieval, and generation into separate services would add
operational complexity (network hops, contracts, deploy units) with
no real performance benefit. A single FastAPI process with clean
internal layering keeps the system understandable while making each
boundary swappable. If, later, ingestion needed to be a batch job and
the API needed to scale horizontally, the layered structure makes it
straightforward to extract `core/ingestion.py` into a worker.

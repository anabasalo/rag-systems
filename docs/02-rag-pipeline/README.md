# Phase 2 — Core RAG Pipeline

This phase closes the loop. After Phase 1 you could turn documents
into searchable chunks; now the system answers questions over those
chunks via an HTTP API, with citations.

## Learning goals

After this phase you can:

- Walk through the full RAG flow: question → embed → retrieve →
  prompt → LLM → grounded answer.
- Explain why citations matter and how the prompt enforces grounding.
- Read the API contract in `docs/00-design/05-api-contract.md` and
  see how each endpoint here implements it.
- Identify the layered architecture in code: HTTP handlers in
  `app/api/*`, business logic in `app/core/*`, persistence in
  `app/db/*`. No layer "skips".
- Recognize when *not* to call the LLM (the empty-context fallback)
  and why that matters for honest answers.

## What was built

| File | Role |
| --- | --- |
| [`app/core/exceptions.py`](../../app/core/exceptions.py) | `CollectionNotFound`, `DocumentNotFound`, `LLMUnavailable` (the API error catalog in code form) |
| [`app/core/retrieval.py`](../../app/core/retrieval.py) | `basic_retrieve`, `build_where_clause`, `post_filter_by_tags` |
| [`app/core/generation.py`](../../app/core/generation.py) | Prompt template, `Generator` Protocol, `GroqGenerator` |
| [`app/schemas.py`](../../app/schemas.py) | Pydantic models matching the API contract |
| [`app/api/deps.py`](../../app/api/deps.py) | FastAPI dependency providers (singletons, override-able in tests) |
| [`app/api/ingest.py`](../../app/api/ingest.py) | `POST /ingest`, `GET /collections`, `GET/DELETE` per-doc endpoints |
| [`app/api/query.py`](../../app/api/query.py) | `POST /query` |
| [`app/main.py`](../../app/main.py) | App factory + exception → HTTP-status handlers |
| [`tests/test_api.py`](../../tests/test_api.py) | 18 end-to-end tests via `TestClient`, Groq mocked |

The architecture invariants from the design doc are now enforced in
code:

- only `app/db/vector_store.py` imports `chromadb`
- only `app/core/generation.py` knows how to talk to Groq
- routes raise typed core exceptions; HTTP status codes are decided
  exactly once, in `app/main.py`

## Walkthrough: a `POST /query` from start to finish

This is the single most important code path in the project. Trace it
once and the rest of the system snaps into place.

```
1. FastAPI dispatches to query_endpoint (app/api/query.py)
2. Pydantic validates QueryRequest:
       - question >= 1 char
       - collection matches COLLECTION_NAME_PATTERN
       - doc_filter (optional) matches DocFilter shape
       - strategy is "basic"
3. basic_retrieve(...) is called (app/core/retrieval.py):
   3a. checks the collection exists in the vector store
       -> raises CollectionNotFound if not, mapped to 404 in main.py
   3b. translates doc_filter into a Chroma `where` clause
       (build_where_clause)
   3c. embeds the question (Embedder dependency)
   3d. asks the vector store for top-K chunks
   3e. if doc_filter has `tags`, post-filters in Python
       (Chroma metadata can't substring-match a CSV string)
4. Apply similarity floor:
   - any chunk with score < settings.similarity_floor is dropped
   - if NO chunks remain, return the safe answer:
       "I cannot answer this question from the provided documents."
     and DO NOT call the LLM (no tokens spent, no hallucination risk)
5. assemble_prompt(question, chunks) builds:
   - a system message instructing grounding + citation behavior
   - a user message containing the chunks numbered [1], [2], ...
6. Generator.generate(system, user) calls Groq (or the test fake)
   - any exception is wrapped in LLMUnavailable -> 502 in main.py
7. The handler builds QueryResponse:
   answer, collection, strategy, sources[], latency_ms, tokens
```

Everything below the API layer is tested without FastAPI. The API
layer is tested without ChromaDB or Groq. That separation is what
makes the suite finish in two seconds.

## API endpoints (quick reference)

```
POST   /ingest                                multipart upload (file, collection, tags)
GET    /collections                           list collections + counts
GET    /collections/{name}/docs               list docs in a collection
DELETE /collections/{name}/docs/{doc_name}    delete one doc
DELETE /collections/{name}                    delete an entire collection
POST   /query                                 ask a question; returns answer + sources
```

Full request/response shapes with examples live in
[`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md).

## How to run it

### One-time setup

```bash
cd /home/albasalo/projects/rag-systems
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# Open .env and set GROQ_API_KEY=... (free key from https://console.groq.com)
```

### Run the test suite

```bash
source .venv/bin/activate
ruff check app tests
ruff format --check app tests
pytest -v
```

Expected: 35 passed (17 from Phase 1 + 18 from Phase 2). The suite
runs in well under five seconds and does not touch the network.

### Run the server locally

```bash
source .venv/bin/activate
HF_HOME=$(pwd)/.cache/huggingface uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive Swagger UI.

### End-to-end smoke test with `curl`

```bash
# 1. Upload a document
curl -X POST http://127.0.0.1:8000/ingest \
     -F "file=@data/raw/sample.md" \
     -F "collection=k8s-demo" \
     -F "tags=scaling,k8s"

# 2. List collections
curl http://127.0.0.1:8000/collections

# 3. List docs inside the collection
curl http://127.0.0.1:8000/collections/k8s-demo/docs

# 4. Ask a question
curl -X POST http://127.0.0.1:8000/query \
     -H "Content-Type: application/json" \
     -d '{
       "question": "How does the Horizontal Pod Autoscaler scale workloads?",
       "collection": "k8s-demo"
     }'

# 5. Ask the same question, scoped to a specific document
curl -X POST http://127.0.0.1:8000/query \
     -H "Content-Type: application/json" \
     -d '{
       "question": "How does the Horizontal Pod Autoscaler scale workloads?",
       "collection": "k8s-demo",
       "doc_filter": {"doc_name": ["sample.md"]}
     }'

# 6. Try an unanswerable question (should decline)
curl -X POST http://127.0.0.1:8000/query \
     -H "Content-Type: application/json" \
     -d '{
       "question": "What is the capital of France?",
       "collection": "k8s-demo"
     }'
```

## Exercises

1. **Make the model decline.** Add an unrelated document (say,
   `cooking.md`) to a *different* collection. Ask it about
   Kubernetes. Confirm the system declines rather than hallucinating.
   Then lower `SIMILARITY_FLOOR` in `.env` to `0.0` and re-run the
   same question. What changes? Why?

2. **Feel the layering.** Edit `app/api/query.py` and try to import
   `chromadb`. Then run `pytest`. Note the architecture is *not*
   enforced by code (Python doesn't stop you), but every test still
   passes — the convention is what holds the system together. Revert.

3. **Read a real prompt.** In a `pytest -v` run, add a `print` to
   `assemble_prompt` and re-run `tests/test_api.py::test_query_includes_chunk_index_in_prompt`.
   Read what actually gets sent to the model. Notice the `[1]`, `[2]`
   labels and the explicit "if not in context, say I cannot answer".

4. **Tune top-K.** Change `TOP_K` in `.env` from `5` to `2`. Re-run a
   query. Compare the `sources` list and the answer. Then try `10`.
   When does the answer get worse? Why?

5. **Swap the LLM.** Set `LLM_MODEL` to `llama-3.1-70b-versatile`
   (still free on Groq). Re-ask the same question. Compare answer
   quality and latency.

## What's next

Phase 3 introduces a second retrieval strategy (`improved`: hybrid
BM25 + vector + MMR re-ranking) and a `POST /compare` endpoint that
runs both side-by-side on the same question. That is where the
"production-shaped" claim earns its keep — you'll see when a richer
retrieval beats pure vector and when it does not.

## Further reading

- [`concepts.md`](concepts.md) — what RAG is, prompt assembly,
  citations, the empty-context fallback
- [`alternatives.md`](alternatives.md) — RAG vs. fine-tuning vs.
  long-context; OpenAI vs. Groq vs. Ollama; prompt template patterns
- [`references.md`](references.md) — papers and official docs
- ADR [`0002`](../00-design/adrs/0002-llm-provider-groq.md) — why Groq
- [`05-api-contract.md`](../00-design/05-api-contract.md) — the
  source of truth for endpoint shapes

# Phase 3 — Retrieval Strategies

Phase 2 wired one retrieval strategy: pure dense (cosine) top-K. That's
enough to *work*, but it has a known weakness — vector retrieval misses
when the question and the document use different words for the same
idea, or when the right answer requires an exact term (a function name,
an error code, a CLI flag) that the embedder happens to encode poorly.

This phase introduces a second strategy, ``improved``, that combines:

- **BM25** keyword retrieval (rewards exact-term overlap)
- **Vector retrieval** from Phase 2 (rewards semantic similarity)
- **Reciprocal Rank Fusion** to merge the two rankings
- **Maximal Marginal Relevance** to remove near-duplicate chunks

It also adds a new endpoint, **`/compare`**, which runs both strategies
on the same question and returns both responses so you can see the
difference yourself.

## Learning goals

After this phase you can:

- Explain the difference between **sparse** (BM25) and **dense**
  (vector) retrieval, and why hybrid usually beats either alone.
- Read [`app/core/retrieval.py`](../../app/core/retrieval.py) and
  follow the chain `vector top-N + BM25 top-N → RRF → MMR → top-K`.
- Justify why we used **Reciprocal Rank Fusion** rather than weighted
  score normalization for combining the two rankings.
- Justify why we used **MMR** for the final re-rank rather than a
  cross-encoder.
- Use `/compare` to study a real case where ``improved`` wins (and to
  notice cases where it does not).

## What was built

| File | Role |
| --- | --- |
| [`app/core/retrieval.py`](../../app/core/retrieval.py) | `tokenize`, `bm25_retrieve`, `reciprocal_rank_fusion`, `mmr_rerank`, `improved_retrieve` |
| [`app/db/vector_store.py`](../../app/db/vector_store.py) | new `get_all_chunks(...)` to fetch the BM25 corpus and MMR embeddings |
| [`app/api/query.py`](../../app/api/query.py) | `/query` now accepts `strategy: "basic" | "improved"`; `POST /compare` runs both |
| [`app/schemas.py`](../../app/schemas.py) | `RetrievalStrategy` literal, `CompareRequest`, `CompareResponse`, `StrategyResult` |
| [`tests/test_retrieval.py`](../../tests/test_retrieval.py) | 12 pure unit tests for `tokenize`, RRF, MMR |
| [`tests/test_retrieval_integration.py`](../../tests/test_retrieval_integration.py) | 10 tests against a real (in-tmp) ChromaDB |
| [`tests/test_api.py`](../../tests/test_api.py) | 5 new HTTP tests for `strategy=improved` and `/compare` |

The architecture invariants from earlier phases still hold:

- `chromadb` is imported only by `app/db/vector_store.py`
- `rank_bm25` is imported only inside `bm25_retrieve` (lazy, scoped)
- API handlers don't know what algorithms run inside retrieval — they
  pass `strategy` and a `RetrievalResult` comes back

## Walkthrough: a `POST /query` with `strategy=improved`

```
1. FastAPI dispatches to query_endpoint (app/api/query.py).
2. _run_strategy(strategy="improved", ...) is called.
3. improved_retrieve(...) runs:
   3a. validate the collection exists -> CollectionNotFound (404) if not
   3b. embed the question (one call to the embedder)
   3c. vector retrieval: top-fetch_k by cosine, applying doc_filter.doc_name
       at the index level via Chroma's `where`
   3d. BM25 retrieval: pull all candidate chunks (respecting doc_filter),
       tokenize them, build a BM25Okapi index, score the question, take
       top-fetch_k
   3e. Reciprocal Rank Fusion fuses the two rankings into one ordered
       list (no score normalization required; only the per-list rank of
       each chunk matters)
   3f. take the top fetch_k of the fused list -- this is our candidate pool
   3g. fetch the candidate pool's embeddings from ChromaDB (one read,
       by ids)
   3h. MMR re-ranks the pool to k chunks, balancing relevance to the
       query against diversity from chunks already chosen
4. Apply similarity floor (same as basic): if no chunk has score >=
   floor, return the safe answer without calling the LLM.
5. assemble_prompt(...) and call the generator (same code path as basic).
6. Return QueryResponse(strategy="improved", ...).
```

Step 3 is the only thing that changed between Phase 2 and Phase 3.
Everything below the strategy boundary — prompt assembly, generation,
floor logic, response shape, exception handling — is the same code.

## API endpoints (delta from Phase 2)

```
POST   /query            +  strategy: "basic" | "improved"  (default "basic")
POST   /compare          NEW.  body = same as /query, minus `strategy`
                                returns { question, collection, basic, improved }
```

Full request/response shapes with examples live in
[`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md).

## How to run it

### Tests

```bash
source .venv/bin/activate
ruff check app tests
ruff format --check app tests
pytest -v
```

Expected: **62 passed** (35 from Phases 1-2 + 27 from Phase 3). Runs in
under 10 seconds, no network.

### Server + curl

Start the server (same as Phase 2):

```bash
source .venv/bin/activate
HF_HOME=$(pwd)/.cache/huggingface uvicorn app.main:app --reload
```

Try the new strategy on a single document corpus:

```bash
# Ingest the sample doc into a fresh collection
curl -X POST http://127.0.0.1:8000/ingest \
     -F "file=@data/raw/sample.md" \
     -F "collection=k8s"

# Same question, two strategies, side by side
curl -X POST http://127.0.0.1:8000/compare \
     -H "Content-Type: application/json" \
     -d '{
       "question": "How does the Horizontal Pod Autoscaler scale workloads?",
       "collection": "k8s"
     }'
```

The `/compare` response carries both `basic` and `improved` results;
each side has its own answer, sources, latency, and token usage.

For a more interesting comparison, ingest several documents (so the
strategies have room to disagree about which to retrieve):

```bash
for f in data/raw/*.md; do
  curl -X POST http://127.0.0.1:8000/ingest \
       -F "file=@$f" \
       -F "collection=mixed"
done
curl -X POST http://127.0.0.1:8000/compare \
     -H "Content-Type: application/json" \
     -d '{"question": "...", "collection": "mixed"}'
```

## Exercises

1. **Prove BM25 earns its keep.** Find or write a question whose
   answer requires a specific term (an acronym, a function name, a CLI
   flag). Compare `strategy=basic` and `strategy=improved`. The
   improved one should pull the chunk containing the exact term,
   even when the embedder doesn't.

2. **Watch MMR matter.** Ingest a document that repeats the same
   passage twice (or upload the same doc under two different names).
   Ask a question that hits the duplicated passage. With basic
   retrieval, you'll see the same chunk content twice in `sources`.
   With improved, MMR should drop one of them in favor of a different
   chunk.

3. **Tune `mmr_lambda`.** It is hard-coded to `0.5` in
   `improved_retrieve`. Edit it to `1.0` (pure relevance) and re-run a
   query you expect to have near-duplicates. Observe the difference.
   Then try `0.3` (more diversity).

4. **Read the actual fused ranking.** In `improved_retrieve`, add a
   `print(fused[:10])` after the RRF step and re-run a `/query`. See
   which chunks each of vector and BM25 contributes, and how RRF
   interleaves them. Remove the print before committing.

5. **Reason about cost.** Phase 2's `/query` makes 1 embedding call +
   1 vector query + 1 LLM call. Phase 3's improved `/query` makes 1
   embedding call + 1 vector query + 1 *full-collection read* (BM25
   corpus) + 1 *id-lookup read* (MMR embeddings) + 1 LLM call. When
   does that overhead become a problem? (Hint: full-collection read.)

## What's next

Phase 4 brings **evaluation**. We'll feed a small Q&A dataset into
`/evaluate`, score each answer with RAGAS metrics
(faithfulness, answer relevancy, context precision/recall), and use
that to decide *empirically* whether `improved` actually beats
`basic` on our corpus. Until you've evaluated, "improved" is just a
name.

## Further reading

- [`concepts.md`](concepts.md) — sparse vs. dense retrieval, BM25
  walkthrough, RRF formula, MMR formula, candidate-pool sizing
- [`alternatives.md`](alternatives.md) — RRF vs. weighted score
  normalization, MMR vs. cross-encoder reranking, query-expansion
  alternatives
- [`references.md`](references.md) — Robertson 1994 (BM25), Cormack
  2009 (RRF), Carbonell 1998 (MMR), Pinecone hybrid-search guides
- ADR [`0001`](../00-design/adrs/0001-vector-db-chromadb.md) — the
  vector store; `get_all_chunks` is built on top of it
- ADR [`0005`](../00-design/adrs/0005-scoping-collections-vs-namespaces.md)
  — `doc_filter` is honored by both basic and improved

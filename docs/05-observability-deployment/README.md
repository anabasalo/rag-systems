# Phase 5 — Observability & Deployment

The system already worked. This phase makes it *operable*.

We add a structured query log so every request leaves a record,
expose `/health` and `/logs` so you can inspect a running instance,
ship a Dockerfile + docker-compose so the whole thing runs in one
command, wire up CI, and polish the top-level README so a stranger
can clone the repo and demo it in five minutes.

## Learning goals

After this phase you can:

- Read the difference between a `/query` log line and an `/evaluate`
  log line in `logs/queries.jsonl` and tell what happened.
- Build, run, and tear down the whole stack with Docker.
- Read the GitHub Actions workflow and understand what it guarantees.
- Justify why we use **structured JSONL logs** rather than
  free-form `print` calls or a metrics-only system like Prometheus.

## What was built

| File | Role |
| --- | --- |
| [`app/observability/query_log.py`](../../app/observability/query_log.py) | `QueryLogger` — append-only JSONL with a soft size cap and a thread lock |
| [`app/api/health.py`](../../app/api/health.py) | `GET /health` — version + collection count |
| [`app/api/logs.py`](../../app/api/logs.py) | `GET /logs?limit=N` — tail the structured log |
| [`app/api/query.py`](../../app/api/query.py) | `/query` and `/compare` now record one log line per request |
| [`app/api/evaluate.py`](../../app/api/evaluate.py) | `/evaluate` records the eval summary on completion |
| [`app/api/deps.py`](../../app/api/deps.py) | `get_query_logger` singleton + test override |
| [`app/scripts/ingest_dir.py`](../../app/scripts/ingest_dir.py) | bulk-ingest script for `data/raw/...` |
| [`Dockerfile`](../../Dockerfile) | two-stage build (builder → runtime) |
| [`docker-compose.yml`](../../docker-compose.yml) | single `api` service with persistent volumes |
| [`.dockerignore`](../../.dockerignore) | keep the build context small |
| [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | ruff + pytest on every push and PR |
| [`README.md`](../../README.md) | top-level overview, quick start, demo, layout, links |
| [`tests/test_observability.py`](../../tests/test_observability.py) | 9 logger unit tests (append, tail, malformed lines, size cap) |
| [`tests/test_api.py`](../../tests/test_api.py) | 13 new API tests for `/health`, `/logs`, and the wiring |

The architecture invariants from earlier phases still hold:

- The logger is a single file under `app/observability/`. Nothing else
  imports `json.dumps` for logging purposes.
- The API handlers depend on a `QueryLogger` *instance*, not on the
  filesystem; the test fixture injects a tmp-path logger.
- `/health` and `/logs` follow the same router → schema pattern as the
  rest of the API.

## Walkthrough: what gets logged for each endpoint

Every entry is a single JSON object on its own line:

```json
{
  "ts": "2026-05-04T22:50:01.123456+00:00",
  "endpoint": "/query",
  "status": "ok",
  "collection": "k8s",
  "strategy": "improved",
  "question": "How does the HPA work?",
  "n_sources": 5,
  "latency_ms": 412,
  "tokens": {"prompt": 725, "completion": 44},
  "error": null,
  "extra": {}
}
```

Per-endpoint specifics:

- **`/query`** — `status` is `"ok"` if the LLM was called, `"declined"`
  if the similarity floor short-circuited.
- **`/compare`** — one line per request; `extra.basic` and
  `extra.improved` carry per-strategy n_sources / latency / tokens.
  The top-level `latency_ms` is the sum of both runs (so the line
  reflects total wall-clock).
- **`/evaluate`** — one line per *call*, not per item. `extra` carries
  `item_count`, `answered_count`, `declined_count`, and the metric
  `summary` block.
- **`/ingest`, `/collections`, `/health`** — *not* logged. They are
  read-only or write-only operations that don't move RAG numbers.

The log is intentionally small in cardinality (10 well-known
endpoints × a handful of statuses); analyzing it with `jq` is
genuinely pleasant.

## Walkthrough: a request through the deployed stack

```
$ curl -X POST http://localhost:8000/query \
       -H "Content-Type: application/json" \
       -d '{"question":"hpa","collection":"k8s"}'

# 1. Docker routes :8000 to the api container.
# 2. uvicorn (single worker) hands the request to FastAPI.
# 3. The /query route resolves Depends(...) for settings, store,
#    embedder, generator, query_logger.
#    First request only: SentenceTransformer model loads from
#    /app/.cache/huggingface (mounted volume -> persists across
#    rebuilds).
# 4. retrieve -> assemble_prompt -> Groq -> response built.
# 5. query_logger.record(...) appends one JSON line to
#    /app/logs/queries.jsonl (mounted to ./logs on the host).
# 6. JSON response goes back to the client.
```

## API endpoints (delta from Phase 4)

```
GET    /health                  liveness + version + collection count
GET    /logs?limit=N            tail of the structured log (limit 1..500)
```

`/query`, `/compare`, `/evaluate` keep their request/response shapes
exactly; the only behavioral change is that they now record a log
line.

## How to run it

### Tests

```bash
source .venv/bin/activate
ruff check app tests
ruff format --check app tests
pytest -v
```

Expected: **99 passed** (80 from Phases 1–4 + 19 from Phase 5).
Still under 15 seconds, still no network calls.

### Local server

Same as before. The server now writes `logs/queries.jsonl` as you use it:

```bash
HF_HOME=$(pwd)/.cache/huggingface uvicorn app.main:app --reload
# ... in another shell, hit /query a few times, then:
curl http://127.0.0.1:8000/logs?limit=5 | jq '.entries[] | {endpoint, strategy, latency_ms}'
```

### Docker

```bash
cp .env.example .env  # set GROQ_API_KEY
docker compose up --build
```

Volumes mounted:

- `./data/chroma` — vector index, persisted across rebuilds
- `./data/raw`, `./data/eval` — corpus + eval set, read-only
- `./logs` — query log, persisted across rebuilds
- `hf_cache` (named volume) — embedding model cache

Health check is wired into the compose file: `docker ps` shows
`(healthy)` once the API is responsive.

### CI

GitHub Actions runs on every push and PR:

1. Set up Python 3.12 with `pip` cache keyed on the requirements
   files.
2. `ruff check` — lint must pass.
3. `ruff format --check` — formatting must be applied.
4. `pytest --maxfail=1` — first failure stops the run.

No `GROQ_API_KEY` is needed in CI — the suite uses the `_FakeScorer`
and `_FakeGenerator` from `tests/conftest.py`. Concurrency is set so
new pushes to a PR cancel the previous run.

## Exercises

1. **Diff two strategies' latency from the logs.** Run the same
   question through `/query` with `strategy=basic`, then again with
   `strategy=improved`. Open `logs/queries.jsonl`. Use `jq` (or
   Python) to compute the average `latency_ms` per `strategy`. The
   improved one will usually be slower because of the extra Chroma
   read; sometimes it is faster because BM25 short-circuited.

2. **Spot a degenerate corpus.** Ingest one document. Hit `/query`
   with three different but related questions. Inspect the logs
   for `n_sources`. If `n_sources == top_k` every time and the
   collection is small, the floor is too low — every chunk is
   "relevant".

3. **Read the Dockerfile critically.** What is the security risk of
   running uvicorn as `root` (which the image does)? What would
   change if you added a non-root user? *Hint: bind mounts inherit
   the host's UID.*

4. **Force a CI failure.** Open a PR that introduces a deliberate
   ruff violation (e.g. an unused import). Confirm the CI run goes
   red. Fix it; confirm it goes green. The whole loop should take
   under 90 seconds.

5. **Add a new field.** Suppose you wanted to log the *first* doc_name
   in the sources for every `/query`. Find the spot in
   `app/api/query.py` where `query_logger.record(...)` is called and
   add `doc_name=sources[0].doc_name if sources else None`. Where
   does the schema for that field need to change? (Trick question —
   it doesn't, because `LogEntry` has `extra: Allow`.) Pin the
   behavior with a test.

## What's next (post-course follow-ups)

The project is now demoable end to end. Real-product follow-ups,
in rough order of impact:

- **Per-item streaming on `/evaluate`** so a 30-item run isn't a
  4-minute wait with no feedback.
- **Refusal-correctness metric** alongside RAGAS, so declined items
  don't pull averages down. (See `docs/04-evaluation/alternatives.md`.)
- **Cross-encoder reranking** behind the `improved` strategy if eval
  shows context_precision is the ceiling.
- **Two-vector-DB story**: a swappable backend (`pgvector`,
  Elasticsearch) by re-implementing `app/db/vector_store.py`.
- **OpenTelemetry traces** in addition to the JSONL log, for
  multi-process / multi-instance deployments.

Each of these is purely additive to the architecture this course built.

## Further reading

- [`concepts.md`](concepts.md) — structured logging, why JSONL beats
  free-form, observability vs. monitoring, the role of `/health`
- [`alternatives.md`](alternatives.md) — JSONL vs. SQLite vs.
  Prometheus vs. OpenTelemetry; in-handler vs. middleware logging;
  Docker single-stage vs. two-stage
- [`references.md`](references.md) — Twelve-Factor, Google SRE book,
  observability classics
- [`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md)
  — the source of truth for `/health` and `/logs` shapes

# Phase 5 — Alternatives

For each design choice this phase introduced, this document records
the alternatives that were considered, the trade-off that was made,
and the conditions under which the alternative would have been the
better answer.

## Alternative 1 — Where to record log entries

We **call `query_logger.record(...)` inside each handler**. The
serious alternatives:

### FastAPI / Starlette middleware

Wrap every request in a `BaseHTTPMiddleware` that builds the log
entry from the request and response. Looks elegant and would centralize
logging.

The problem is access:

- The request body has *already been consumed* by the handler by the
  time the middleware sees the response. Reading it again requires
  buffering, which doubles memory for large uploads.
- The middleware has no visibility into handler-internal data:
  `n_sources`, `tokens`, `strategy`, `declined`. It would have to
  parse the response JSON to extract them, which is fragile.
- Errors that bubble up as HTTP exceptions reach the middleware as
  HTTPExceptions, *after* the typed core exception is gone.

In-handler logging is more verbose (one explicit call per endpoint)
but the log entry can include exactly the fields that matter to that
endpoint. Worth the four extra lines per route.

### A logging decorator

```python
@log_request(endpoint="/query")
def query_endpoint(...): ...
```

Cute, but suffers the same access problem as middleware: the
decorator sees the request and the return value but not the
intermediate state.

### Structured logging via Python's `logging` module

`logging.getLogger(...).info(...)` with a JSON formatter. Standard
practice for ops-style services.

Avoided here because:

- Python `logging` has *thread-local* state and per-process global
  configuration; FastAPI's threadpool sometimes makes the level /
  handler configuration drift mid-request.
- We want the log file to be the canonical artifact, not stderr.
  `logging` can be configured to do that, but it is several lines
  of `dictConfig` per environment.
- A 60-line bespoke `QueryLogger` is more legible than the same
  functionality wrapped in `logging` plumbing.

If the project grew, ditching `QueryLogger` for
`logging` + `python-json-logger` + a SQS / Kafka handler is a clean
migration. The endpoint-side code (`logger.record(...)`) does not
need to change — only `app/observability/query_log.py` does.

## Alternative 2 — Log storage backend

We chose a **plain JSONL file**. Considered:

### SQLite

One row per request, schema-validated. Allows joins, indexes,
ad-hoc SQL.

- ✅ Better for analytical queries past ~100k entries.
- ❌ Not append-only; concurrent writes need careful WAL config.
- ❌ Schema migrations turn into a problem when log shape evolves.
- ❌ Loses self-descriptiveness (you need the schema *plus* the
  data to interpret a row).

For our scale, the JSONL file is `cat`-able, `jq`-able, `wc -l`-able.
SQLite earns its keep past tens of millions of rows.

### Prometheus / StatsD (counters only)

Increment a counter per request, expose `/metrics`. Standard for
service health.

- ✅ Cheap, real-time, plays well with Grafana.
- ❌ Lossy by design — you cannot recover *which* request caused a
  latency spike.
- ❌ Doesn't store the question, the collection, or the answer.

Metrics complement logs; they don't replace them. If we needed a
dashboard, we'd add a metrics layer alongside the JSONL log.

### OpenTelemetry traces

The "real" answer for distributed systems. One trace per request,
spans for retrieval / generation / scoring.

- ✅ Lets you debug *causally* ("retrieval was the slow step
  yesterday at 3pm").
- ❌ Heavy: collector container, exporter config, span SDK in code.
- ❌ Overkill for a single-process service.

If the system grows to multi-instance, OpenTelemetry is the
natural next step. The current JSONL log is essentially a
zero-overhead stub of an OTel span exporter.

### A managed log service (Datadog, CloudWatch, Loki)

The grown-up answer. Ship logs out of the container, let the
service do retention, indexing, and alerting.

- ✅ Search at scale, alerting, retention policies handled.
- ❌ Costs money and a vendor.
- ❌ Network dependency for what is otherwise a self-contained
  project.

Plug-in point: add an HTTP-shipping handler in
`app/observability/query_log.py` (alongside the file write) and
the rest of the system doesn't notice.

## Alternative 3 — How `/logs` returns data

Today: `GET /logs?limit=N` reads the file, parses it, returns the
last `N` entries as JSON.

Alternatives considered:

### Streaming SSE / chunked response

Return entries as they're parsed. Useful when `limit` is large
(tens of thousands).

- ✅ Lower memory peak server-side.
- ❌ Adds client-side complexity for a feature whose primary user
  is `curl | jq`.

We capped `limit` at 500. At that size, "load it all and serialize"
is fine.

### Parameterized filtering (`?endpoint=/query&min_latency=1000`)

Let the user query the log via URL params.

- ✅ Convenient.
- ❌ Reinvents `jq`. The output is JSONL anyway; piping through `jq
  'select(.endpoint == "/query")'` is one command.

If a later phase adds a UI, server-side filtering becomes
worthwhile. For now the API is intentionally minimal.

### `tail -f` semantics (long-poll / WebSocket)

A live tail of the log over the network. Useful for demos.

- ✅ Slick.
- ❌ Adds connection-management complexity for something already
  available via `docker compose logs -f` or `tail -f logs/queries.jsonl`.

## Alternative 4 — Single-stage vs. two-stage Dockerfile

We chose **two-stage**. Considered:

### Single stage

Install everything in one `FROM python:3.12-slim`. Simpler to read.

- ✅ Fewer lines.
- ❌ Runtime image carries `gcc`, `build-essential`, and pip's
  caches. Image grows by ~500 MB. CVE surface grows accordingly.
- ❌ Not reproducible: re-running the Dockerfile will pull whatever
  pip resolves *now*, not what the wheels resolved at build time.

### Distroless or scratch

Use Google's `distroless/python3` or `scratch` for the runtime image.

- ✅ Smallest possible image, smallest CVE surface.
- ❌ Can't `docker exec` into the running container for debugging;
  no shell.
- ❌ Some Python packages (chromadb, ragas) have transitive C
  dependencies that distroless doesn't ship.

Two-stage with `python:3.12-slim` is the pragmatic middle. We can
debug interactively when we need to; the runtime image is ~600 MB
mostly from PyTorch / sentence-transformers, which is hard to
shrink without losing the embedder.

## Alternative 5 — uvicorn vs. gunicorn-managed uvicorn

We use **bare `uvicorn` with one worker**. Production guides usually
recommend `gunicorn -k uvicorn.workers.UvicornWorker --workers N`.

The difference is process management:

- `gunicorn` runs N worker processes; the master restarts crashed
  workers.
- `uvicorn` alone runs one process; if it dies, the container dies
  and Docker / Kubernetes restarts it.

For a containerized single-instance service, the second model is
*better* — Docker is the process manager. Multiple uvicorn workers
inside one container would multiply the embedding model's memory
footprint (each worker loads its own copy of `all-MiniLM-L6-v2`).

If you scale horizontally, you scale the *container* count, not
worker count per container.

## Alternative 6 — How we test the logger wiring

We use the **fixture override** approach: `tests/conftest.py`
provides a `tmp_query_log` fixture and `client` injects it via
`app.dependency_overrides`. Tests assert against
`client.query_log.tail(...)`.

Alternatives considered:

### Mock the logger entirely

Replace `QueryLogger` with `MagicMock`. Tests assert on `.record(...)`
call args.

- ❌ Couples tests to argument names.
- ❌ Doesn't exercise the file write path.
- ❌ Mocks lie: a refactor that introduces a real bug can leave the
  mock-call count unchanged.

### Write to the real `logs/queries.jsonl` and clean up

Simplest. Tests pollute the host filesystem.

- ❌ Test order dependent. A failed test leaves stale data.
- ❌ Parallel test runs (pytest-xdist) would race on the same file.

The `tmp_query_log` fixture writes to a per-test directory and never
collides. The `tail()` reads the same bytes the production code
would read; nothing is mocked.

## Alternative 7 — CI scope

We run **lint + format + tests** in CI. Considered adding:

### A live `/evaluate` smoke test

Run a real query against Groq, assert latency < N seconds.

- ❌ Requires `GROQ_API_KEY` as a secret. Easy to leak via a
  contributor's PR.
- ❌ Adds vendor flakiness (Groq's free tier is rate-limited).
- ❌ Costs LLM tokens per CI run.

Manual smoke testing is fine for a study project; for a real
product, run the live test on `main` only (post-merge) with a
team-owned API key.

### Coverage gating (`pytest --cov --cov-fail-under=85`)

- ✅ Catches new code without tests.
- ❌ Coverage is a *correlate* of quality, not the goal. Chasing a
  number leads to test cruft.

Skipped, by deliberate choice. We have ~99 tests, every behavior
the project claims is pinned by name; the next failure mode would
be silently *removing* tests, which a coverage tool wouldn't catch
either.

### Container build in CI

`docker build .` to verify the Dockerfile still works.

- ✅ Catches Dockerfile regressions before deploy.
- ❌ The build is slow (~90 seconds) and loads CI minutes.

Worth adding once a deployment target exists. For now the local
`docker compose up --build` covers the use case.

## Alternative 8 — Top-level README structure

We picked **overview → quick start → demo → endpoints → layout**.
Considered:

### Tutorial-first

Walk the reader through building a small piece. Excellent for
adoption, but it duplicates `docs/0X-*/`. The course already serves
that audience.

### Reference-first

Lead with the API contract. Good for users coming from `curl`. We
linked it instead and put the contract in `docs/00-design/05-api-contract.md`,
which is the single source of truth.

The chosen shape gets a stranger from `git clone` to a working
demo in five minutes. That is the most common first session and
the one the README should optimize for.

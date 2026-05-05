# Phase 5 — Concepts

Plain-language explanations of why the production-ish bits of this
project are shaped the way they are.

## Observability vs. monitoring

These words get used interchangeably; they are not the same.

- **Monitoring** — *known unknowns*. Pre-defined dashboards and
  alerts. "CPU > 80% for 5 minutes" is monitoring. You knew
  beforehand that CPU mattered.
- **Observability** — *unknown unknowns*. The ability to ask
  arbitrary questions about a running system after the fact.
  "Why did latency spike for users in collection X yesterday at
  3pm?" is an observability question.

The distinction matters because they need different inputs:

| Monitoring | Observability |
| --- | --- |
| Aggregated metrics (Prometheus) | Per-event records (logs, traces) |
| Pre-aggregated; low cardinality | Raw; high cardinality |
| Cheap, real-time | Costlier, search-style |
| "Is the system OK?" | "What is the system doing?" |

Phase 5 ships **observability primitives** — one structured record
per request — and one **monitoring primitive** — `/health`. We
didn't add Prometheus because, at this scale, the JSONL log can
answer every question Prometheus could *and* the questions
Prometheus cannot ("show me every `/query` against collection
`legal-2024-Q3` that returned 0 sources").

## Why JSONL, specifically

A structured log line is a JSON object. JSONL ("JSON Lines") is just
"one JSON object per line, separated by `\n`". The format has three
properties that matter:

1. **Append-only.** Writes don't move existing bytes. POSIX guarantees
   atomicity for writes ≤ `PIPE_BUF` (4 KB on Linux), which is more
   than enough for our entries. No locking required between
   processes; we use a thread lock only because FastAPI's sync
   handlers run in a threadpool.

2. **Streamable.** Tools like `jq`, `grep`, `tail -f`, `wc -l` work on
   it directly. You don't need to parse the file as a whole — each
   line is independently valid JSON.

3. **Self-describing.** The keys are in the data, not in a schema
   file. A log entry from six months ago is still meaningful even
   if the code has moved on.

Compare to alternatives:

| Format | Append-only | Streamable | Self-describing | Notes |
| --- | --- | --- | --- | --- |
| Free-form `print` | yes | partially | no | grepping with regex; bad for analytics |
| SQLite | no (B-tree updates) | no | yes (schema) | one schema migration to break logs |
| Plain JSON (one big array) | no (must rewrite the array) | no | partial | unusable for tail / append |
| **JSONL** | **yes** | **yes** | **yes** | what we picked |
| Parquet | yes (segment-style) | partially | yes (schema) | overkill for <10 MB of logs |

For a project of our size, JSONL is the smallest tool that works.

## The shape of a "good" log entry

What goes in the entry is more important than the format. Two heuristics:

1. **One entry should be enough to reconstruct the request.** If you
   need to read three other systems to understand what happened, the
   entry is too thin. We log: endpoint, status, collection,
   strategy, question, n_sources, latency, tokens, error. That is
   enough to answer almost any post-hoc question.

2. **Avoid *PII* and *huge fields*.** We log the question (which is
   user-typed and could contain anything) but not the full retrieved
   chunks (which can be megabytes). For a real product you would
   either hash questions or omit them; we keep them because this is
   a study project and the corpus is public docs.

A small list of fields, every time, with sensible nulls for fields
that don't apply, is more useful than a sprawling per-endpoint
schema. That's why `/compare` and `/evaluate` use the same shape and
overflow into `extra`.

## Health checks

`/health` looks trivial. It is, on purpose. The endpoint should:

- be **fast** (single-digit ms; we count collections, which is one
  SQLite read in Chroma).
- be **safe to call repeatedly** (idempotent, no side effects).
- **never depend on the LLM**. If Groq is down, the system is
  *degraded*, not unhealthy. The container is still alive and it
  is still answering. We surface "Groq is down" as a 502 on the
  endpoints that need it; we do *not* fail the health check.

`/health` is the contract Docker, Kubernetes, load balancers, and
human operators all read to decide "is this instance worth routing
traffic to?". If the answer mixes in "and is the LLM working?", you
end up taking the system out of rotation for a vendor incident,
which is rarely what you want.

The version field on the response lets a deploy be confirmed from
outside ("did the new image actually start?") without trusting the
build pipeline.

## Container image discipline

The Dockerfile is two-stage:

1. **Builder stage** — has gcc, build-essential, the full pip
   toolchain. Builds wheels for sentence-transformers and
   pdfplumber (which have native components).
2. **Runtime stage** — slim base image, no compiler, just the
   wheels and the application code.

Two consequences:

- The runtime image is **smaller**. Less network, fewer CVEs,
  faster `docker pull`.
- The runtime image cannot rebuild itself. If a dependency updates,
  CI rebuilds from scratch, the wheels regenerate, the runtime
  image gets the new wheel. Builds are reproducible.

We do not run as a non-root user. For a study project mounted via
bind volumes (which inherit the host's UID), this is the simpler
choice; for production it would be a single-line change
(`USER nobody` and a chowned `/app`).

## Why `docker-compose.yml` even though it is a single service

Compose buys three things even with one service:

1. **Volume management is declarative.** The yaml says exactly which
   host paths map to which container paths. No three-line `docker
   run` command to remember.
2. **`.env` is loaded automatically.** No `--env-file` flag.
3. **Health checks live with the service.** The `healthcheck:` block
   makes the running container self-report `(healthy)`.

When a future phase adds a second service (say, a UI, or a
Postgres-based metadata store), compose extends naturally; the
single-service version is a one-line addition rather than a port
from `docker run`.

## Why CI even at this size

The four-line CI workflow guarantees three things:

1. **`ruff check` passes.** Style and obvious bugs.
2. **`ruff format --check` passes.** No "I forgot to format"
   commits.
3. **`pytest` passes.** No "I forgot to run tests" commits.

The cost is ~90 seconds of CI minutes per PR. The benefit is that
**main is always green**. That makes bisecting bugs trivial, and
makes "merge this" require zero risk-assessment for code quality.

We do not run integration tests against real Groq in CI. The fakes
in `tests/conftest.py` cover the wiring; live-API testing is
manual and deliberate (it costs LLM tokens and adds flakiness from
vendor downtime).

## The query log as the seed of an eval pipeline

There's an underrated property of the structured log: it is
*already* a record of every (question, collection, strategy,
n_sources, latency) tuple the system has handled. With one Python
script, last month's user questions become next quarter's eval
dataset.

That's the shape of a real RAG operation:

```
production traffic → query log → curated questions → eval set → CI
                                                             ↓
                                                "did this PR regress?"
```

We don't ship the loop here, but the JSONL log is exactly the file
the loop needs as input. That is the difference between
"observability for debugging" and "observability for product
quality".

## When to graduate from this setup

The current setup is right for: a solo project, a small team, a
single instance. It will start to creak when:

- **You have multiple instances.** Tail-and-grep across N hosts is
  unpleasant. Ship logs to a central store (Loki, Elasticsearch,
  CloudWatch, BigQuery).
- **You need traces.** Cross-component latency questions ("retrieval
  was 100ms, generation was 400ms, but total was 2s — where did the
  rest go?") require *traces*, not logs. OpenTelemetry is the right
  next step; it can co-exist with the JSONL log.
- **You need real metrics.** Counts and percentiles over time
  (p50/p95/p99 latency) want a metrics backend, not a log
  aggregator. Prometheus + Grafana is the standard.

All three are additive. None of them require rewriting what we have.

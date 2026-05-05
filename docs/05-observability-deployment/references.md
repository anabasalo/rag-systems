# Phase 5 — References

Curated reading for observability, structured logs, container
discipline, and CI for small services.

## Foundational reading

- **Beyer, Jones, Petoff & Murphy (Google), 2016 — *Site
  Reliability Engineering*.**
  https://sre.google/books/
  Free online. Chapters 6 (Monitoring Distributed Systems) and 12
  (Effective Troubleshooting) are the practitioner's handbook for
  the monitoring/observability split discussed in `concepts.md`.

- **Wiggins, 2011 — *The Twelve-Factor App*.**
  https://12factor.net/
  Short and dated in places, but the constraints it codifies
  ("treat logs as event streams", "store config in the
  environment", "stateless processes") are the reason this
  project's Dockerfile and `app/config.py` look the way they do.

- **Charity Majors — *Observability — A 3-Year Retrospective*.**
  https://charity.wtf/2020/11/02/observability-a-3-year-retrospective/
  The case for high-cardinality logs (and structured events) over
  pre-aggregated metrics. Directly motivates the JSONL choice.

- **Cindy Sridharan, 2018 — *Distributed Systems Observability*
  (O'Reilly free e-book).**
  https://www.oreilly.com/library/view/distributed-systems-observability/9781492033431/
  Chapters 4 (Logs) and 6 (Tracing) are the canonical "what each
  pillar is good for" reference.

## Practical guides

- **OpenTelemetry — *Concepts*.**
  https://opentelemetry.io/docs/concepts/
  When you graduate from "JSONL logs in one process" to "traces
  across services", this is the standard. Its log SDK can ingest
  the JSONL we already produce.

- **Loki — *Best Practices*.**
  https://grafana.com/docs/loki/latest/best-practices/
  Tail-end story: how to ship JSONL-style logs to a central store
  without giving up `grep`-style ergonomics. Loki indexes labels,
  not full text — a good fit for our small, well-known field set.

- **Docker — *Multi-stage builds*.**
  https://docs.docker.com/build/building/multi-stage/
  The exact pattern our `Dockerfile` uses.

- **Docker — *Best practices for writing Dockerfiles*.**
  https://docs.docker.com/develop/develop-images/dockerfile_best-practices/
  Cache ordering (copy `requirements.txt` before code), `USER`
  guidance, and the ENV layering rules.

- **GitHub Actions — *Caching dependencies to speed up workflows*.**
  https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows
  Why our workflow keys the `pip` cache on the requirements files.

- **GitHub Actions — *Concurrency*.**
  https://docs.github.com/en/actions/using-jobs/using-concurrency
  The concurrency block we use to cancel superseded runs.

## Library / tool references

- **`uvicorn` — deployment.**
  https://www.uvicorn.org/deployment/
  When to graduate to gunicorn, what `--workers` actually does,
  and why we don't use it inside a single container.

- **FastAPI — testing dependencies.**
  https://fastapi.tiangolo.com/advanced/testing-dependencies/
  The `dependency_overrides` mechanism the test client uses to
  inject `_FakeGenerator`, `_FakeScorer`, and `tmp_query_log`.

- **Python `pathlib` — `write_text` / `read_text`.**
  https://docs.python.org/3/library/pathlib.html
  Underpins `QueryLogger`. Note the `encoding="utf-8"` argument we
  pass everywhere — `encoding=None` would default to the locale,
  which has caused real bugs.

## Books

- **Kim, Humble, Debois & Willis — *The DevOps Handbook*, 2nd ed.**
  https://itrevolution.com/the-devops-handbook/
  Chapter 14 (Telemetry) is a friendly companion to the SRE book,
  with more on the cultural side of "what to do with the data once
  you have it".

- **Burns, Beda, Hightower — *Kubernetes Up and Running*, 3rd ed.**
  https://www.oreilly.com/library/view/kubernetes-up-and/9781098110192/
  Useful even if you stay on Docker: the chapter on liveness vs.
  readiness probes is the source for the "don't fail health on LLM
  outage" rule we follow in `/health`.

## Adjacent reading worth a skim

- **Charity Majors — *Logs vs. Structured Events*.**
  https://www.honeycomb.io/blog/logs-vs-structured-events
  The pithy version of the JSONL argument.

- **Brendan Gregg — *USE Method*.**
  https://www.brendangregg.com/usemethod.html
  Short methodology for analyzing performance — applies to RAG
  latency just as well as to OS performance.

- **Google — *Building Secure & Reliable Systems*, Chapter 6 (Design
  for Understandability).**
  https://sre.google/books/building-secure-reliable-systems/
  The argument for making systems easy to reason about *as a
  design constraint*, not as a nice-to-have.

## Project artifacts

- [`docs/00-design/03-architecture.md`](../00-design/03-architecture.md)
  — the layering this phase respects.
- [`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md)
  — `/health` and `/logs` shapes (the source of truth).
- [`tests/test_observability.py`](../../tests/test_observability.py)
  — every behavior the logger claims to support has a named test.
  The size-cap test is the most informative: it documents the
  truncation rule by exercising it.
- [`Dockerfile`](../../Dockerfile),
  [`docker-compose.yml`](../../docker-compose.yml),
  [`.dockerignore`](../../.dockerignore) — read in that order.
- [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) — the
  three-step contract that keeps `main` green.

# rag-systems

A production-shaped Retrieval-Augmented Generation (RAG) service built
incrementally as a study project. It ingests documents, answers
questions over them with citations, lets you compare retrieval
strategies, scores answer quality with RAGAS, and ships with structured
logs, a health check, Docker, and CI.

The project doubles as a self-paced course. Every phase has working
code, unit tests, and a `docs/0X-*/` folder explaining what was built,
why, and what alternatives existed. See [`docs/README.md`](docs/README.md)
for the learning path.

## What it does

- **Ingest** PDFs, Markdown, and text files into named, scoped
  collections.
- **Query** with citations: each answer references the chunks used,
  and the system declines (without calling the LLM) when retrieval
  finds nothing relevant.
- **Compare** two retrieval strategies on the same question:
  - `basic` — pure dense (cosine) top-K
  - `improved` — hybrid BM25 + vector → Reciprocal Rank Fusion → MMR
- **Evaluate** with RAGAS metrics (faithfulness, answer relevancy,
  context precision/recall) and an aggregate summary.
- **Observe** every request via a structured JSONL log; tail it via
  `GET /logs`.

## Architecture in one line

```
api/  ──►  core/  ──►  db/      (and eval/, observability/)
```

`api/` does FastAPI; `core/` is the only place that knows about LLMs,
embeddings, retrieval and prompt assembly; `db/` is the only place that
imports `chromadb`. Tests inject fakes through FastAPI's dependency
overrides and never call Groq or RAGAS. The architecture document is
in [`docs/00-design/03-architecture.md`](docs/00-design/03-architecture.md).

## Quick start (local)

Prerequisites: Python 3.11+, a free Groq API key from
[console.groq.com](https://console.groq.com).

```bash
git clone https://github.com/<your-fork>/rag-systems.git
cd rag-systems

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# edit .env and set GROQ_API_KEY=gsk_...

# Run the test suite (no network, no GPU; ~10s)
pytest -v

# Start the API
HF_HOME=$(pwd)/.cache/huggingface uvicorn app.main:app --reload
```

The first request that needs an embedding will download a small
sentence-transformers model (~80 MB) into `.cache/huggingface/`.

Open `http://127.0.0.1:8000/docs` for an interactive Swagger UI.

## Quick start (Docker)

```bash
cp .env.example .env  # set GROQ_API_KEY
docker compose up --build
# in another shell
curl http://localhost:8000/health
```

Persistent state (ingested chunks, query logs) lives in `./data/chroma/`
and `./logs/` on the host. `docker compose down` does not delete it.

## 2-minute demo

```bash
# 1. Ingest the K8s autoscaling sample
curl -X POST http://localhost:8000/ingest \
  -F "file=@data/raw/sample.md" \
  -F "collection=k8s"

# 2. Ask a grounded question
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"How does the Horizontal Pod Autoscaler work?","collection":"k8s"}'

# 3. Show the system declining when it should
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the capital of France?","collection":"k8s"}'

# 4. Compare retrieval strategies side-by-side
curl -X POST http://localhost:8000/compare \
  -H "Content-Type: application/json" \
  -d '{"question":"horizontal pod autoscaler","collection":"k8s"}'

# 5. Score the system on a small eval set (takes 2-4 minutes; 4 RAGAS metrics × N items)
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "collection":"k8s",
    "strategy":"basic",
    "items":[
      {"question":"What does HPA do?","ground_truth":"HPA scales pod replicas based on observed metrics."},
      {"question":"What is the capital of France?","ground_truth":"I cannot answer this question from the provided documents."}
    ]
  }'

# 6. Inspect what the service has been doing
curl http://localhost:8000/logs?limit=10
```

## Endpoints

| Method | Path | What |
| --- | --- | --- |
| POST | `/ingest` | Upload a doc into a collection |
| GET | `/collections` | List collections + counts |
| GET | `/collections/{name}/docs` | List docs in a collection |
| DELETE | `/collections/{name}/docs/{doc_name}` | Remove one doc |
| DELETE | `/collections/{name}` | Remove a whole collection |
| POST | `/query` | Ask a question (`strategy: basic \| improved`) |
| POST | `/compare` | Run both strategies, return both answers |
| POST | `/evaluate` | RAGAS scoring of a small Q&A batch |
| GET | `/health` | Liveness + version + collection count |
| GET | `/logs?limit=N` | Tail of the structured query log (capped at 500) |

Full request/response shapes with examples live in
[`docs/00-design/05-api-contract.md`](docs/00-design/05-api-contract.md).

## Bulk-ingest

```bash
python -m app.scripts.ingest_dir --dir data/raw --collection demo --recursive
```

The script ingests every `.md`, `.txt`, and `.pdf` under the directory
into one collection. Re-runs are idempotent (each doc is replaced by
its newest version).

## Repository layout

```
.
├── app/
│   ├── api/            FastAPI routers (one file per endpoint group)
│   ├── core/           pure logic: chunking, embedders, retrieval, generation, exceptions
│   ├── db/             ChromaDB wrapper (the ONLY place that imports chromadb)
│   ├── eval/           dataset loader, Scorer Protocol, RagasScorer, runner
│   ├── observability/  structured JSONL query log
│   ├── scripts/        operational scripts (ingest_demo, ingest_dir)
│   ├── config.py       Pydantic Settings loaded from .env
│   ├── main.py         app factory + global exception → HTTP-status mapping
│   └── schemas.py      Pydantic request/response models
├── data/
│   ├── raw/            sample documents (committed)
│   ├── eval/           eval Q&A datasets (committed)
│   └── chroma/         vector index (gitignored, runtime-only)
├── docs/               the course (one folder per phase)
├── logs/               query logs (gitignored, runtime-only)
├── tests/              pytest suite (no network, no real LLM, ~10s)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml      ruff config, pytest config
├── requirements.txt
└── requirements-dev.txt
```

## Where the design choices are written down

- [`docs/README.md`](docs/README.md) — the course index and learning path
- [`docs/00-design/`](docs/00-design/) — vision, requirements, architecture, ADRs, glossary
- [`docs/01-ingestion/`](docs/01-ingestion/) — parsing, chunking, embeddings, vector stores
- [`docs/02-rag-pipeline/`](docs/02-rag-pipeline/) — FastAPI, prompt assembly, citations, the empty-context fallback
- [`docs/03-retrieval-strategies/`](docs/03-retrieval-strategies/) — BM25, RRF, MMR
- [`docs/04-evaluation/`](docs/04-evaluation/) — RAGAS metrics, LLM-as-judge, refusal correctness
- [`docs/05-observability-deployment/`](docs/05-observability-deployment/) — structured logs, Docker, CI

## Development

```bash
# Lint + format
ruff check app tests
ruff format app tests

# Tests
pytest -v

# Run one phase's docs alongside the code:
$EDITOR docs/02-rag-pipeline/concepts.md
```

CI runs the same three commands on every push and PR; the workflow
file is at [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## License

This project is intended as a study artifact and currently ships
without an explicit license. Add one before re-using.

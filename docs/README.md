# rag-systems — A Hands-On Course on Building RAG

This folder is a self-paced course built into the project. It mirrors the
implementation phases under `app/` and explains both *what* the system does
and *why* each design decision was made.

If you have never built a Retrieval-Augmented Generation (RAG) system, start
with Phase 0 and walk through each phase in order. Every phase ships:

- working code under `app/` (and matching tests under `tests/`)
- a course folder under `docs/0X-*` with concepts, walkthroughs, alternatives,
  and references

## What you will learn

By the end of the course you will be able to:

- explain how RAG works end-to-end (ingestion → retrieval → generation)
- choose between chunking, embedding, and retrieval strategies and justify
  the trade-offs
- evaluate the quality of a RAG system with reproducible metrics
- run the system locally as a containerized service with structured logs

## Prerequisites

- comfort with Python 3.11+
- basic understanding of HTTP and JSON
- a terminal, `git`, and Docker (Docker only required from Phase 5)
- a free Groq API key (for the LLM call). Sign up at
  [console.groq.com](https://console.groq.com)

You do **not** need a GPU. Embeddings run on CPU using a small
sentence-transformers model.

## Learning path

| Phase | Folder | Topic | Time |
| --- | --- | --- | --- |
| 0 | [`00-design/`](00-design/) | Vision, requirements, architecture, ADRs | ~3 h |
| 1 | `01-ingestion/` | Parsing, chunking, embeddings, vector stores | ~6 h |
| 2 | `02-rag-pipeline/` | FastAPI, prompt assembly, citations | ~6 h |
| 3 | `03-retrieval-strategies/` | BM25, hybrid retrieval, MMR re-ranking | ~6 h |
| 4 | `04-evaluation/` | RAGAS, faithfulness, context precision | ~4 h |
| 5 | `05-observability-deployment/` | Structured logging, Docker, CI | ~5 h |

Phases 1–5 will be added as the project is built. This document tracks the
intended scope; the source of truth for what is implemented is the code in
`app/` and the tests in `tests/`.

## How each phase doc is organized

Every phase folder follows the same shape so you always know where to look:

- `README.md` — learning goals, what was built, walkthrough, exercises
- `concepts.md` — the theory behind the phase
- `alternatives.md` — what else we could have used and why we did not
- `references.md` — papers, official docs, and recommended reading

## Glossary

A short reference for common terms is in
[`00-design/glossary.md`](00-design/glossary.md).

## Conventions

- Code blocks are runnable unless explicitly marked otherwise.
- File paths are relative to the repository root (the parent of `docs/`).
- ADRs (Architecture Decision Records) live under
  [`00-design/adrs/`](00-design/adrs/) and follow a Context / Decision /
  Consequences / Alternatives format.

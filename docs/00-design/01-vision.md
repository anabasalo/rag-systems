# Vision

## Problem statement

Large language models are excellent at generating fluent text but poor at
remembering facts they were not trained on, and they routinely hallucinate
when asked questions about private or domain-specific information. The
practical answer used in industry is **Retrieval-Augmented Generation
(RAG)**: ground the model in a curated corpus by retrieving the most
relevant chunks at query time and feeding them into the prompt.

`rag-systems` is a small, production-shaped RAG service that demonstrates
the full lifecycle of such a system over engineering documentation: how
documents are ingested and indexed, how questions are scoped and routed
through different retrieval strategies, how answers are grounded in
citations, and how the quality of those answers can be evaluated.

## Target reader and use case

The intended reader is an engineer who wants to understand how RAG systems
work end-to-end and to have a working reference implementation they can
extend. The system answers questions over a small corpus of engineering
documentation (for example: a Kubernetes guide, an AWS whitepaper, an API
reference) and shows the reader, alongside each answer, which chunks were
retrieved and how the answer would have differed under a different
retrieval strategy.

## Success criteria

The project is successful when all of the following are true:

1. A user can upload a PDF, Markdown, or text document into a named
   collection and immediately query it.
2. A query returns an answer plus the chunks used to produce it
   (citations), within ~2–3 seconds on a typical laptop.
3. The same query can be run against two retrieval strategies and the
   user can inspect both answers and both source lists side by side.
4. An evaluation endpoint produces faithfulness and relevance scores for
   a question, including the case where the corpus does not contain the
   answer (the system should decline rather than fabricate).
5. The whole system runs with `docker compose up` and a single `.env`
   file, requiring no paid services.
6. A reader can follow `docs/` from Phase 0 to Phase 5 and understand
   every decision the project makes.

## Non-goals

Explicitly out of scope:

- **Authentication and multi-tenancy.** There are no user accounts and no
  authorization checks. Anyone with network access to the service can
  read or modify any collection.
- **A polished web frontend.** The product surface is a JSON HTTP API.
  A minimal Streamlit page is allowed only as an optional stretch in
  Phase 5.
- **Real-time streaming responses.** Answers are returned in a single
  response; token streaming is not implemented.
- **Horizontal scaling and orchestration.** No Kubernetes manifests, no
  load balancer config, no autoscaling. The system is designed to run as
  one container.
- **Long-term document versioning.** Re-ingesting a document overwrites
  the previous chunks; there is no history.
- **Fine-tuning or training of any model.** Embedding and generation
  models are used as-is.

## Demo narrative (the 2-minute walkthrough)

The intended walkthrough of a finished system, used to drive the design:

1. *Setup.* `docker compose up`. The service is reachable at
   `localhost:8000`. The `kubernetes-docs` collection has been pre-seeded
   from `data/raw/`.
2. *Ask a grounded question.* `POST /query` with
   `{"question": "How does Kubernetes handle pod scaling?",
   "collection": "kubernetes-docs"}`. The response shows an answer
   plus 3–5 cited chunks with their source filenames.
3. *Compare retrieval strategies.* `POST /compare` with the same
   question. The response contains two answers side by side (basic
   cosine vs. hybrid BM25 + vector + MMR) and shows that the chunk lists
   differ.
4. *Show the "I don't know" property.* Ask a question that is not in the
   corpus. The system declines to answer rather than hallucinating, and
   `/evaluate` reports a low faithfulness score for an answer that does
   try to invent.
5. *Show observability.* `GET /logs?limit=5` returns the last queries
   with their latency, retrieved chunk IDs, and strategy used.

This narrative is the contract the rest of the design has to satisfy.

# Phase 2 — Concepts

Plain-language explanations of the ideas this phase relies on.

## What is RAG (Retrieval-Augmented Generation)?

LLMs have two modes of "knowing" things: parametric memory (what they
learned during training) and in-context (what you put in the prompt).
Parametric memory is fixed at training time, can be wrong, and you
cannot inspect or update it cheaply. In-context is fresh, attributable,
and trivially updateable — but the prompt has to be assembled at query
time.

**RAG** is the pattern of *fetching the right context at query time
and putting it in the prompt*. The system stops being "an LLM that
guesses" and becomes "an LLM grounded in a curated corpus".

Three ingredients, in order:

1. **R — Retrieve**. Use a vector store (and/or keyword index) to
   pull the K most relevant chunks for the user's question.
2. **A — Augment**. Concatenate those chunks into a prompt with
   instructions about how to use them.
3. **G — Generate**. Call the LLM. It produces an answer.

The whole project up to this phase has been "everything you need
*before* the G". Phase 1 produced the searchable index. Phase 2 wires
the retriever, the prompt assembler, and the generator into one
HTTP endpoint.

## Why not just fine-tune the model?

Three practical reasons (see also `alternatives.md`):

- **Freshness.** Adding a document to RAG is `POST /ingest`, takes
  seconds, and is reversible. Fine-tuning is a training run.
- **Attribution.** RAG can show *which chunks* produced an answer.
  A fine-tuned model cannot tell you which training example was
  responsible.
- **Cost.** Fine-tuning is expensive in compute and in iteration
  speed. Retrieving from a vector store is cheap.

Fine-tuning is still the right answer for *style*, *behavioral
constraints*, or *domain-specific syntax* the model has never seen.
For *facts about your documents*, RAG wins almost every time.

## Why citations?

Citations are not decoration. They serve three functions:

1. **Trust.** The user can verify the answer by reading the cited
   chunks. This is the difference between "the model says" and
   "the model says, and here is where".
2. **Debugging.** When an answer is wrong, you immediately see
   whether the retrieval was wrong (no relevant chunk was found)
   or the generation was wrong (the right chunk was there but the
   model misread it). Without citations these failure modes are
   indistinguishable.
3. **Grounding pressure.** A model instructed to cite is, in
   practice, less likely to hallucinate. Citing forces it to attach
   each claim to a chunk; if no chunk supports the claim, it is
   structurally harder to invent one.

In this project every successful `/query` response includes a
`sources` array. Each entry has the chunk id, the originating
document name, the chunk index, the cosine score, and the actual
chunk text. The frontend (or curl user) can render these alongside
the answer.

## Prompt assembly

`assemble_prompt(question, chunks)` produces two messages:

- **System.** A small, deliberate instruction:
  - answer using ONLY the provided context
  - if the context does not contain the answer, reply with the
    exact safe phrase
  - cite chunks by their bracketed index `[n]`
  - do not invent facts

- **User.** The chunks (numbered `[1]`, `[2]`, ...) followed by the
  question and a short "Answer:" hint.

The choices here are small but deliberate:

- **Numbered chunks.** The model is told to cite by number. This is
  more reliable than asking it to remember filenames precisely.
- **Source label per chunk.** Each chunk is prefixed with
  `(source: <doc_name>)`. The model can mention the filename when it
  helps the reader; it does not have to.
- **Explicit refusal phrasing.** The system message gives the model
  *exact* words to use when it cannot answer. Without this, models
  tend to either over-decline ("I don't have enough information")
  or hallucinate. A fixed refusal string is also evaluable in Phase 4.
- **Temperature 0.** Set in `GroqGenerator.__init__`. Determinism
  matters for evaluation and debugging. There is no creativity tax
  for technical Q&A.

## The empty-context fallback (FR-3.3)

This is the single most undervalued part of a production RAG system.
If retrieval returns nothing relevant — no chunks above the similarity
floor — *we do not call the LLM at all*. The handler returns the safe
phrase directly.

Why does this matter?

1. **No tokens spent on a question we cannot answer.** Calling the
   LLM with empty or irrelevant context wastes money and adds
   latency.
2. **Hallucination prevention.** With no context, the model would
   answer from parametric memory — exactly the failure mode RAG is
   supposed to avoid.
3. **Honest signal in eval.** Phase 4 will measure how often the
   system correctly declines. Without this fallback, the metric is
   meaningless because the model would be answering from prior
   knowledge.

The behavior is pinned by `test_query_below_floor_returns_safe_answer_without_calling_llm`
in [`tests/test_api.py`](../../tests/test_api.py): when the floor is
high enough that nothing passes, the test asserts both the safe
answer string AND that the fake generator was never called.

## Context window

Every LLM has a maximum input length, measured in *tokens*. Llama 3
8B on Groq accepts 8,192 tokens of input + output combined. With our
defaults — 5 chunks of ~512 tokens each = ~2,500 tokens of context,
plus the question, plus the system prompt, plus headroom for the
answer — we are comfortably under the limit.

But this is a real engineering constraint, not a footnote:

- **Increasing top-K** makes prompts longer, slower, and more
  expensive. The "Lost in the Middle" paper (see `references.md`)
  shows quality also gets worse past a certain point because the
  model attends less to chunks in the middle of a long context.
- **Increasing chunk size** has the same problem on a different
  axis.
- **Decreasing top-K** can starve the answer of context. There is no
  free lunch.

This is exactly the kind of trade-off Phase 4's evaluation is
designed to expose.

## The layered architecture, in code

The architecture document has a diagram. The code makes it real.
Read this list and confirm it for yourself by grepping:

- `from fastapi import ...` appears only under `app/api/`,
  `app/main.py`, and `app/schemas.py`.
- `import chromadb` appears only in `app/db/vector_store.py`.
- `from groq import Groq` appears only in `app/core/generation.py`.
- `app/core/*.py` does not know FastAPI exists.
- `app/db/*.py` does not know FastAPI exists.

Each of these is one boring rule that, taken together, means *every
external dependency can be swapped without touching the rest*. That
is what "layered" buys you.

## Dependency injection in FastAPI (the why behind `Depends`)

You will see `vector_store: VectorStore = Depends(get_vector_store)`
in every API handler. This is FastAPI's idiom for inversion of
control. Three benefits:

1. **Singletons by default.** `get_vector_store` is `@lru_cache`d, so
   every request gets the same `VectorStore` instance. The embedding
   model is loaded once per process, not per request.
2. **Override-able for tests.** `app.dependency_overrides[...] =
   ...` swaps the real provider for a fake without monkeypatching.
   This is what `tests/conftest.py::client` uses to inject the fake
   embedder, fake generator, and tmp ChromaDB.
3. **Composability.** A handler can declare exactly what it needs.
   No global state to mock, no implicit context.

If you have used Spring or Guice, this is the same idea, just lighter.

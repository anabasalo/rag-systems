# Phase 2 — Alternatives

For each design choice in the RAG pipeline this phase introduces, this
document records the alternatives that were considered, the trade-off
that was made, and the conditions under which the alternative would
have been the better answer. Read it after `concepts.md`.

## Alternative 1 — RAG vs. fine-tuning vs. long-context prompting

We chose RAG. The two serious alternatives were:

### Fine-tuning

Take a base model and continue training it on your documents until the
weights "remember" them.

| Dimension | RAG | Fine-tuning |
| --- | --- | --- |
| Add a new document | `POST /ingest`, seconds | new training run |
| Remove a document | `DELETE`, seconds | retrain from scratch (unforgetting is hard) |
| Show *why* the model said X | citations, exact chunks | not possible |
| Compute cost | embedding + cheap retrieval | GPU hours per update |
| Fits a 1–2 week project | yes | no |
| Works for *style* / *behavior* (e.g. always reply in JSON) | weakly | strongly |
| Works for *facts in your docs* | strongly | weakly without retrieval anyway |

Fine-tuning is the right tool when you need the model to *behave*
differently — speak in a tone, follow a schema, use a domain syntax
the base model has never seen. It is the wrong tool for "the model
should know what is in these PDFs". For that, RAG is faster, cheaper,
auditable, and updateable in production.

In real systems the two are not exclusive: you fine-tune for
behavior, you RAG for facts.

### Long-context prompting ("just stuff all the docs in")

Modern models (GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro) accept
hundreds of thousands of tokens. So why retrieve at all? Just include
the corpus in every prompt.

It works for tiny corpora and falls apart everywhere else:

- **Cost scales with every request.** Prompt tokens are the dominant
  cost. Putting 30 PDFs in *every* request is wasteful when only one
  contains the answer.
- **"Lost in the Middle" effect.** Liu et al. (2023) showed that
  models attend much less to information in the middle of long
  contexts. Quality goes *down*, not just speed.
- **Latency.** Prompt-processing time grows with input length.
- **It does not scale.** "Stuff all docs" stops working at the moment
  your corpus exceeds the context window — usually within weeks of
  real use.

RAG is the disciplined version: instead of "include everything", we
include "the smallest subset of chunks that is likely to contain the
answer". The vector store is what makes that affordable.

When long-context wins: small static corpora (tens of pages),
prototyping, or *combined with* RAG (retrieve top-50 and let the
long-context model do the final filtering).

## Alternative 2 — LLM provider

ADR [`0002`](../00-design/adrs/0002-llm-provider-groq.md) is the
authoritative comparison. In short:

| Provider | Free? | Latency | Cost | Privacy | Picked? |
| --- | --- | --- | --- | --- | --- |
| **Groq (Llama 3.1 8B Instant)** | yes (with rate limit) | ~200–500ms | $0 in dev | data sent to Groq | ✅ |
| OpenAI (gpt-4o-mini) | no, but cheap | ~500–1500ms | ~$0.15/M in | sent to OpenAI | considered |
| Anthropic (Claude Haiku) | no | ~700ms | similar | sent to Anthropic | considered |
| Ollama (local Llama / Mistral) | yes | seconds without GPU | $0 | local | not for this project |
| HF Inference API | yes (limited) | variable | rate-limited | sent to HF | rejected (rate limits) |
| Self-hosted (vLLM / TGI) | depends | fastest at scale | infra cost | local | overkill |

The key constraint was "free, fast, and good-enough quality". Groq
hits all three. The honest cost: Groq's free tier is rate-limited and
their model lineup changes (we already had to swap from
`llama3-8b-8192` to `llama-3.1-8b-instant` because the first was
deprecated mid-build — see ADR 0002). For a real product, having
**two** providers behind a single `Generator` Protocol matters more
than which one is "best".

This is exactly why `app/core/generation.py` defines the `Generator`
Protocol — adding `OpenAIGenerator` later is one file.

## Alternative 3 — Prompt template style

We use a **system + user** two-message prompt with numbered chunks.
Other valid styles:

### Single user message with everything inline

```
You are a helpful assistant... [instructions] ...
Context: ... [chunks] ...
Question: ...
Answer:
```

Simpler, but mixes instructions and data. Some models pay less
attention to instructions when they are far from the end of the
prompt; instruction-following degrades.

### Few-shot examples

```
Q: "What is X?"  Context: ...  A: "X is..."
Q: "What is Y?"  Context: ...  A: "..."
Q: <real question>
```

Strong choice when the model needs to learn an output *shape*
(e.g. always return JSON, always use a specific citation format).
Costs more tokens per request and only helps when the format is
non-trivial. For free-form prose answers with citations it is
unnecessary.

### Tool-calling / function-calling

The model is given a `retrieve(query)` tool and decides itself when
to call it (a.k.a. "agentic RAG"). More flexible (multi-hop questions,
follow-up retrieval), much more complex to build, and frequently
slower or buggier than a single retrieve-then-generate pass.

We picked the simplest thing that produces grounded answers and
explicit refusals. If Phase 4 finds the eval is bottlenecked by
multi-hop questions, this is the obvious next step.

## Alternative 4 — How the empty-context fallback is implemented

Three places we *could* have put the "don't answer if no context" rule:

1. **Only in the system prompt.** Tell the LLM: "if no chunks contain
   the answer, say `I cannot answer...`". Cheap to write. Wastes a
   model call on a question we know we cannot answer. Models also
   sometimes ignore this and confabulate.
2. **In the prompt + as a hard short-circuit before the LLM call.**
   Drop chunks below the similarity floor; if nothing remains, return
   the safe answer directly without calling Groq.
3. **Only as a hard short-circuit (no system instruction).** Cheaper,
   but the LLM will sometimes still hallucinate when context exists
   but does not actually answer the question.

We chose **(2)**. The system prompt enforces grounding even when
context exists; the floor handles the "no relevant context at all"
case without spending tokens. Both layers cooperate.

The smoke test from Phase 2 demonstrates this empirically: asking
"What is the capital of France?" against a Kubernetes corpus returns
the safe answer in **13ms** with **zero tokens used**, because the
floor caught it.

## Alternative 5 — How `doc_filter` is enforced

Three options for filtering retrieval to a subset of docs:

1. **Push the filter to the vector DB.** ChromaDB supports a `where`
   clause: `where={"doc_name": {"$in": ["a.md", "b.md"]}}`. The
   filter happens at the index level.
2. **Retrieve top-K then filter in Python.** Pull top-K, drop chunks
   that do not match.
3. **Pre-filter the index by collection only; ignore doc_filter.**
   Easiest, but useless when the user wants to scope to 3 of 30 docs.

We chose **(1) for `doc_name` and `doc_id`** because Chroma's `where`
clause is purpose-built for this and it preserves the top-K semantics
correctly (after filtering you still get K *matching* chunks, not
K-minus-non-matches). For **`tags`** specifically we use **(2)**
because tags are stored as a CSV string (e.g. `"scaling,k8s"`) and
Chroma's metadata filter does not substring-match; teaching it to
would require splitting tags into one row per (chunk, tag), which is
storage we did not want yet.

The trade-off: if you scope by 50 tags out of a million chunks, the
post-filter approach is wasteful (you fetch up to top-K * inflation
chunks and discard most). For a study project with hundreds of
chunks this is invisible. ADR
[`0005`](../00-design/adrs/0005-scoping-collections-vs-namespaces.md)
covers this in more depth.

## Alternative 6 — Where to map exceptions to HTTP status codes

Two reasonable places:

1. **Inside each route.** Every handler does its own
   `try/except CollectionNotFound: raise HTTPException(404, ...)`.
2. **Globally, via `app.add_exception_handler` in `app/main.py`.**
   Routes raise the typed core exception and never mention HTTP.

We chose **(2)**. Reasons:

- The mapping is in **one place** — the API contract literally
  becomes a Python file the rest of the system imports.
- `app/core/*` stays HTTP-agnostic. The same `CollectionNotFound`
  raised by a CLI script would simply print a friendly error.
- New endpoints inherit the mapping for free.

The cost: when reading a single handler you cannot see "this returns
a 404 if X" without consulting `main.py`. We considered this an
acceptable trade for a single source of truth.

## Alternative 7 — Validating collection names with a regex vs. relying on Chroma

ChromaDB rejects collection names shorter than 3 characters or
containing certain characters. We *could* let Chroma raise its own
error and translate that.

Instead we declared `COLLECTION_NAME_PATTERN` in
[`app/schemas.py`](../../app/schemas.py) and applied it via Pydantic
on every endpoint that accepts a collection name. Reasons:

- **Fail at the boundary.** The user gets a clean 422 with a clear
  message *before* any work is done.
- **The contract is documented.** The OpenAPI spec generated by
  FastAPI shows the regex. The frontend can validate client-side too.
- **Defense in depth.** If we swap Chroma for another vector store
  with different rules, our contract does not silently change.

Without this, Phase 2's API tests would have failed against
ChromaDB's "name too short" error in a way that confused the
*caller* about whose fault it was.

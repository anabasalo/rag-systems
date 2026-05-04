# Phase 4 — Concepts

How RAGAS scores a RAG system, what each metric means in plain terms,
and where these numbers can — and cannot — be trusted.

## Why automated evaluation at all

Human review is the gold standard. Two senior engineers reading 100
question/answer pairs and rating each on a rubric is the most reliable
RAG evaluation you can do. It is also slow, expensive, and irreproducible
across reviewers.

For everything in between — comparing a tweak, regression-checking a
deploy, ranking strategies — we need an automated metric. The
benchmark-style metrics from classical IR (precision@k, MRR, nDCG) work
fine for *retrieval* but cannot judge whether the *generated answer* is
faithful, relevant, or honest. RAG generation requires a generation-aware
metric.

That is the gap **LLM-as-judge** evaluation fills. We give an LLM the
question, the answer, the retrieved context, and (sometimes) the
ground truth, and ask it to score the answer along several axes.

## RAGAS in one diagram

```
       ┌────────────────────────────────────────────┐
       │  inputs you provide                        │
       │  ─────────────────────────────────────     │
       │  question                                  │
       │  retrieved_contexts (chunks the system     │
       │                       used to answer)      │
       │  response (answer the LLM produced)        │
       │  reference (optional ground truth)         │
       └────────────────┬───────────────────────────┘
                        │
              ┌─────────┴──────────┐
              │  RAGAS metric      │
              │  (each is its own  │
              │  small LLM-judge   │
              │  prompt)           │
              └─────────┬──────────┘
                        │
                        ▼
                  score in [0, 1]
```

The four metrics our project uses are independent and can be enabled
individually. They were chosen because together they cover the four
distinct failure modes of a RAG system.

## Metric 1 — Faithfulness (no ground truth needed)

> **Question it answers:** *Is the answer supported by the retrieved
> chunks, or did the model make things up?*

How RAGAS computes it (simplified):

1. Decompose the answer into **atomic claims** (one statement per
   item, e.g. "the HPA scales pods", "it uses CPU metrics", ...).
2. For each claim, ask the LLM: *can this claim be derived from the
   provided context?* Answer is yes/no.
3. `faithfulness = (# claims supported) / (# total claims)`.

Score interpretation:

- `1.0` — every claim is grounded; no hallucination.
- `0.5` — half the claims have no support in the context.
- `0.0` — the answer is essentially invented.

This is *the* metric for hallucination. If `faithfulness` is high but
the user disagrees with the answer, the disagreement is about the
*corpus*, not the model. If `faithfulness` is low, the LLM is making
things up despite having context — usually fixable with a stricter
prompt or a smaller, less-creative model.

## Metric 2 — Answer relevancy (no ground truth needed)

> **Question it answers:** *Did the answer address the question, or
> did it drift?*

How RAGAS computes it:

1. Have the LLM generate **N alternative questions** that the answer
   would be a plausible response to.
2. Embed all those alternative questions and the original question.
3. `answer_relevancy = mean cosine similarity` between the original
   and the alternatives.

Score interpretation:

- `1.0` — the answer is so directly responsive that any
  back-derived question matches the original.
- `0.7` — the answer is *related* to the topic but does not
  precisely address what was asked.
- `< 0.5` — the answer drifted off-topic.

This catches a different failure mode than faithfulness. An answer
can be perfectly faithful (every claim is in the context) and still
be irrelevant to the question (the model expanded on a related
topic). The two metrics together pin down both axes.

## Metric 3 — Context precision (needs ground truth)

> **Question it answers:** *Of the chunks we retrieved, were they
> actually useful for answering this question?*

How RAGAS computes it:

For each retrieved chunk in rank order, the LLM is asked whether the
chunk is relevant to the ground-truth answer. The score is a
rank-weighted precision: chunks judged relevant *near the top* count
more than ones near the bottom.

Score interpretation:

- `1.0` — every retrieved chunk was relevant, top-ranked first.
- `0.5` — half the chunks were noise, or relevant chunks were buried
  below irrelevant ones.
- `0.0` — none of the retrieved chunks helped.

This is a **retrieval quality metric**. If `context_precision` is low
but `faithfulness` and `answer_relevancy` are high, retrieval pulled
junk *and* the model still found the answer somehow — you got lucky.
If both are low, retrieval is the bottleneck.

## Metric 4 — Context recall (needs ground truth)

> **Question it answers:** *Did retrieval find the chunks the
> ground-truth answer is based on?*

How RAGAS computes it:

1. Decompose the **ground truth** into atomic claims.
2. For each claim, the LLM is asked whether the retrieved context
   contains evidence supporting it.
3. `context_recall = (# ground-truth claims supported by context) /
   (# total ground-truth claims)`.

Score interpretation:

- `1.0` — every fact in the ground truth was retrievable.
- `0.5` — half the facts were missed.
- `0.0` — the chunks the system retrieved had nothing to do with
  the ground truth.

This is **the other half of retrieval quality**. Precision asks
"is what we got useful?". Recall asks "did we miss what we needed?".
Both can be low (retrieval is broken), only precision can be low
(noisy retrieval), only recall can be low (we missed key chunks),
or both can be high.

## A worked example: declined questions

This is where eval gets philosophical. Consider:

- *Question:* "What is the capital of France?"
- *Ground truth:* "I cannot answer this question from the provided
  documents."
- *System output:* "I cannot answer this question from the provided
  documents." (correctly declined via the similarity floor)

The system did exactly the right thing. RAGAS, however, sees:

- `retrieved_contexts = []` (we short-circuited before retrieval
  populated the prompt)
- `response = "I cannot answer..."`
- `reference = "I cannot answer..."`

Most metrics need contexts to work meaningfully. `context_precision`
is `0.0` (nothing was retrieved), `context_recall` is `0.0` (the
ground-truth claims are not in the empty context), `faithfulness` is
`0.0` (the answer claims nothing the empty context supports).

**Reading the numbers**: low scores on declined items are *not* a
RAG failure. They are a measurement edge case. The right way to
read an eval run with declined items is to look at:

1. Per-item scores for the *answered* questions.
2. The `declined_count` — and whether it matches the number of
   genuinely unanswerable questions in the dataset.
3. (Manually) check that decline happened on the right items.

A more sophisticated future version would add a separate **refusal
correctness** metric (binary: did the system decline iff the ground
truth is "I cannot answer..."?) and exclude declined items from the
RAGAS averages. See `alternatives.md`.

## Why the LLM-as-judge approach works (and where it doesn't)

The trick that makes RAGAS plausible is that **judging is easier than
generating**. Asking an LLM "does this answer support this claim?" is
a closed task with a yes/no output; the model rarely confabulates a
"yes" out of nothing. It is dramatically more reliable than asking
the same model to *answer* the question would be.

Where it still struggles:

- **Subjective questions.** "Is this explanation good?" depends on
  the audience.
- **Long-form answers.** The atomic-claim decomposition gets noisy
  past about 200 tokens.
- **Domain expertise.** The judge is an LLM. It does not have your
  internal documentation. It will mis-judge claims that are *true
  but unusual* in your domain.
- **The judge model itself.** Free-tier judges (we use Groq's small
  Llama) are noticeably less reliable than GPT-4-class judges. The
  RAGAS paper used GPT-4 as judge. Expect ±10% variance in our
  scores compared to a stronger judge.

This is not a reason not to evaluate. It is a reason to *pair*
automated eval with occasional human review and to track scores as
a *trend over time*, not as absolute truth.

## The eval flow in code

```
1.  data/eval/*.jsonl                    -- you author the dataset
2.  app.eval.dataset.load_dataset        -- read JSONL into EvalItems
3.  app.eval.runner.run_evaluation       -- for each item:
        a. retrieve (basic | improved)
        b. apply similarity floor (decline if needed)
        c. assemble_prompt + generator.generate
        d. collect (Q, A, contexts, GT)
4.  scorer.score(items)                  -- RAGAS via Groq LLM
        each metric runs its own LLM-judge prompt
5.  aggregate per-metric averages        -- ignoring None values
6.  EvaluateResponse                     -- per item + summary
```

Notice what is *not* in this flow: the API layer, ChromaDB, the LLM
provider, RAGAS itself. They live behind interfaces (`Generator`,
`VectorStore`, `Embedder`, `Scorer`). That is what made it possible
to add a 3-step LLM-judged pipeline to the project without changing
how `app/core/` is shaped.

## Why we did not write our own metrics from scratch

We could have. A few homegrown heuristics get you surprisingly far:

- **Ground-truth substring overlap** for context recall.
- **Answer-length sanity check** (refusals are short).
- **Citation count** (each `[n]` corresponds to a real chunk).
- **Answer-vs-question embedding cosine** for relevancy.

These cost zero LLM calls. They are also blind to the kind of
hallucinations we actually need to catch. RAGAS is the right
abstraction for an evaluation phase whose goal is to *teach* RAG
metrics. Once you understand what each RAGAS metric is doing, you
can decide where homegrown metrics buy enough quality at a fraction
of the cost — see `alternatives.md`.

## How RAGAS is wired into this project

A short tour for the curious:

- `RagasScorer.__init__` is cheap. It records the API key, the
  model, and our `Embedder`. No LLM call yet.
- The first `score()` call constructs `LangchainLLMWrapper(ChatGroq(...))`
  and `LangchainEmbeddingsWrapper(_LangchainEmbedderAdapter(embedder))`.
  The adapter is a 5-line class that exposes our `Embedder.embed`
  through langchain's two-method `Embeddings` interface. *No second
  embedding model is loaded.*
- For each item, RAGAS builds a `SingleTurnSample` and the four
  metric implementations each issue their own prompts to Groq.
- Results land in `EvaluationResult.scores` — one dict per item.
- The runner normalizes that into our `EvaluateResultItem` shape and
  computes the summary averages.

If you ever need to swap the LLM judge to OpenAI or another
provider, the change is one constructor in `RagasScorer._ensure_ready`.
The `Scorer` Protocol stays the same; nothing above it cares.

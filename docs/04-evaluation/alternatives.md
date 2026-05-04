# Phase 4 — Alternatives

For each design choice in the evaluation pipeline this phase
introduces, this document records the alternatives that were
considered, the trade-off that was made, and the conditions under
which the alternative would have been the better answer.

## Alternative 1 — RAGAS vs. custom heuristic metrics

We chose **RAGAS**. The serious alternatives:

### Hand-rolled heuristics with no LLM

A surprising amount of signal can come from cheap, deterministic
checks:

| Heuristic | What it catches |
| --- | --- |
| ground-truth substring in answer | basic factual overlap |
| ground-truth substring in retrieved context | crude context recall |
| answer length under N tokens | implicit refusal detection |
| number of `[n]` citations | answers that forgot to cite |
| answer-vs-question cosine (using our embedder) | crude answer relevancy |

These cost zero LLM calls and run in milliseconds. They are blind to
the failure modes that matter most for a *production* RAG system —
hallucinations that paraphrase the corpus correctly but say something
wrong, or answers that drift on-topic without addressing the question.

### LLM-as-judge with a hand-written prompt

We could have skipped RAGAS and written a single judge prompt:

> *Given Q, A, contexts, GT — score on 0-10 for: faithfulness,
> relevance, completeness. Return JSON.*

It works. It is also a research project of its own:

- The prompt has to be carefully tuned to avoid the LLM's bias toward
  giving everything a 7.
- Combining multiple axes into one prompt makes scores correlated
  (the model reasons about all of them together).
- Without RAGAS' decomposition into atomic claims, faithfulness
  scores drift heavily on long answers.

### TruLens / DeepEval / Phoenix

Other open-source RAG eval frameworks. TruLens is older and uses a
different metric vocabulary. DeepEval covers more model-eval ground
than RAG-specific eval. Arize Phoenix is more focused on
observability and drift than on metric scores.

We picked RAGAS because:

- It implements *exactly* the four metrics we wanted, all
  LLM-judged with sensible decomposition prompts.
- Its `evaluate(...)` API takes a dataset + LLM + embeddings and
  returns a results object — the integration is one function call.
- The community has converged on it for academic reproducibility.

The honest cost of RAGAS: heavier dependency footprint, slower
imports, and the per-metric prompts are *hard-coded* in the library
(you cannot easily customize them without forking). For a study
project that's a feature; for a production deployment with a domain
where the default prompts misfire, you would write your own.

## Alternative 2 — Free Groq judge vs. GPT-4-class judge

We use **Groq Llama 3.1 8B Instant** as the judge LLM. RAGAS' own
benchmarks were validated with GPT-4. The choice has consequences:

| Dimension | GPT-4-class | Groq Llama 8B (ours) |
| --- | --- | --- |
| Score *accuracy* (vs. human judges) | ~0.85 correlation | ~0.7 correlation |
| Cost per 1k items | tens of dollars | free (rate-limited) |
| Latency per item | seconds | sub-seconds |
| Reproducibility across runs | medium (deterministic with seed) | medium |

For comparing strategies on the *same* dataset, this is fine — the
judge's bias affects both strategies equally, so the *delta* is
still informative. For absolute scores ("our system is at 0.92
faithfulness"), the absolute number is fuzzier than a paper would
report.

If you need a stronger judge later, the only change is the
`ChatGroq(...)` line in `RagasScorer._ensure_ready`. Swap for
`ChatOpenAI(model="gpt-4o-mini")` (or any langchain chat model).
Everything else — prompts, dataset shape, runner, API contract —
stays the same.

## Alternative 3 — Embedding model for the judge

RAGAS needs embeddings (notably for `answer_relevancy`, which embeds
generated paraphrases of the question). We re-use the project's
`SentenceTransformerEmbedder` via a five-line `_LangchainEmbedderAdapter`.

Two alternatives:

### `langchain-huggingface` HuggingFaceEmbeddings

The "obvious" answer. Adds a dependency, downloads (or re-uses)
the same `all-MiniLM-L6-v2` model, but loads it as a *second*
instance unless we fight the wiring. We did not want a second
copy of the same weights in memory.

### OpenAI embeddings

`text-embedding-3-small` is cheap and high quality. Pulls a second
provider into the eval path; needs a second API key. Rejected for
the same reason ADR 0003 picked an open-source embedder for the
main pipeline: predictability and offline-friendly tests.

The adapter approach gives us: one model in memory, no extra
dependency, the same embeddings used for retrieval *and* eval (so a
test that runs the same query through retrieval and through eval
uses identical vectors).

## Alternative 4 — Where the eval dataset lives

We chose **JSONL files under `data/eval/`**. The contenders:

### Hard-coded Python list in a fixture

Simplest. Versioned with the code. Painful to add 10 new questions —
git diffs are noisy and reviewing the *content* of the dataset
becomes reviewing Python syntax.

### YAML / TOML

More human-friendly than JSON. Adds a parser dependency. Multi-line
strings (which ground truths often are) are easier in YAML, harder
to escape correctly in JSON.

### A small SQLite or DuckDB file

What you'd reach for past a few hundred items. Allows joins (`questions
× strategies × runs → results`). Overkill at our scale; we have 8
items.

JSONL won because:

- One question per line means git diffs are clean.
- No third-party parser needed (`json.loads` per line).
- It is the same format we'd use to ship eval results back out of
  the system (one JSONL line per scored item).
- Tools like `jq` work on it directly.

The schema is two fields (`question`, optional `ground_truth`).
Future fields (e.g. `tags`, `expected_strategy`) can be added
backward-compatibly.

## Alternative 5 — How declined items are scored

Today: the runner short-circuits on the similarity floor, returns the
safe phrase, passes empty contexts to RAGAS, and RAGAS scores those
items at 0.0 across the board. Documented in `concepts.md` as a known
edge case.

Alternatives:

### Skip declined items entirely

Drop them from the scorer call. Pro: no zeros pulling down averages.
Con: you lose the count of declined items in the metric averages,
and a system that *over-declines* (declines on answerable questions)
gets rewarded for it.

### Score declined items with a separate "refusal correctness" metric

Add a binary check: did the system decline iff the ground truth is
the safe phrase? Compute precision/recall on that. Run it alongside
the four RAGAS metrics.

```
                     decline?
                  yes        no
gt = safe        TP         FN  -- failed to decline
gt = answerable  FP         TN  -- correctly answered
                ↑
       refusal precision = TP / (TP + FP)
       refusal recall    = TP / (TP + FN)
```

This is the right answer. It is a planned follow-up — out of scope
for Phase 4 because:

- It would expand the API contract (a new metric in `summary`).
- The `Scorer` Protocol is currently RAGAS-shaped; adding a metric
  the LLM judge does not produce means the runner would have to
  splice scores from two sources.
- The fix is small once the Phase 5 logging lands and we have data
  to validate against.

For now: when your dataset contains declined items, *read the
per-item table*, not the summary.

## Alternative 6 — Per-strategy comparison endpoint

We exposed `/evaluate` with a `strategy` parameter. To compare
basic vs. improved you call it twice. Three other shapes were
considered:

### `/evaluate/compare` (mirrors `/compare`)

Run both strategies in one call, return both summaries. Doubles the
LLM cost of a single endpoint call but matches the pattern from
Phase 3.

### `strategy: "all"`

Same idea, single endpoint, more options. Encourages users to think
of strategies as a closed list, which they aren't if a future
phase adds more.

### Server-side caching of eval runs

Most eval calls hit the same dataset twice (once per strategy). We
could cache the (collection, strategy, dataset_hash) tuple to skip
re-running. Avoids the doubled cost. Adds correctness pitfalls
(cache invalidation when the corpus changes).

We picked the simple `/evaluate` per-strategy approach because:

- It composes: the user can A/B *any* set of strategies (today two,
  tomorrow more) without an API change.
- It keeps each call's cost predictable — a 10-item evaluation
  costs ~10×4 LLM calls, full stop.
- A future `/evaluate/compare` is purely additive.

## Alternative 7 — Synchronous vs. async / streaming eval

Today `/evaluate` is fully synchronous and can take 2-4 minutes
for 10 items. That is fine for the demo (the user runs it once and
shows the summary). It is not fine for an actual product.

Two natural improvements:

### Server-Sent Events / streaming

Return per-item scores as they arrive. The client can render a
progress bar. Implementation: refactor the runner to a generator
that yields one `EvalRunItemResult` at a time; the endpoint streams
those.

### Background jobs + a results table

`POST /evaluate` enqueues, returns a job ID; `GET /evaluate/{id}`
polls. Standard pattern, requires a job queue (Celery, RQ, or even
SQLite + a poll loop).

Both are deferred to Phase 5+. The current design makes them
additive — `run_evaluation` is already side-effect free and the
core orchestration is already separated from the FastAPI handler.

## Alternative 8 — Persisting eval results

We do not persist them today. The user runs `/evaluate`, looks at
the JSON, decides what to do next. For a one-off comparison this
is fine; for a project that ships, you want a history:

- "Did this PR regress faithfulness on the autoscaling dataset?"
- "Show the trend of context_precision over the last 30 days."

This is exactly the kind of question Phase 5's structured logging is
designed to enable. The eval runner already returns a clean
dataclass (`EvalRunResult`) — appending it to a JSONL log is one
line. Wait until Phase 5 to wire that, so the same logging
infrastructure handles `/query` traffic *and* eval runs.

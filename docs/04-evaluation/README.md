# Phase 4 — Evaluation

Up to Phase 3 the system *worked*. After Phase 3 we had two retrieval
strategies — `basic` and `improved` — and no objective way to say
which is better. This phase fixes that.

We add a **`POST /evaluate`** endpoint that, given a small set of
question–reference-answer pairs, runs the full RAG pipeline and
reports per-item scores using **RAGAS** metrics, plus aggregate
averages. The same endpoint can score either strategy. Run it twice,
compare the numbers, and "improved is better" is no longer a vibe —
it's a measurement.

## Learning goals

After this phase you can:

- Explain the four core RAGAS metrics — **faithfulness**,
  **answer relevancy**, **context precision**, **context recall** —
  and what failure mode each one catches.
- Read the eval flow in code: dataset → `run_evaluation` → `Scorer`
  → aggregate. No FastAPI, no ChromaDB, no RAGAS imports outside
  their owning modules.
- Construct a small JSONL eval set with realistic ground-truth
  answers, including unanswerable questions.
- Recognize the limitations of LLM-judged metrics and decide when
  human review or alternative metrics are needed.

## What was built

| File | Role |
| --- | --- |
| [`app/eval/dataset.py`](../../app/eval/dataset.py) | `EvalItem`, `load_dataset` (JSONL, with validation errors) |
| [`app/eval/scorer.py`](../../app/eval/scorer.py) | `Scorer` Protocol, `RagasScorer` (Groq + project embedder via langchain wrappers) |
| [`app/eval/runner.py`](../../app/eval/runner.py) | `run_evaluation` orchestrator: retrieve → generate → score → aggregate |
| [`app/api/evaluate.py`](../../app/api/evaluate.py) | `POST /evaluate` |
| [`app/api/deps.py`](../../app/api/deps.py) | `get_scorer` singleton with test override hook |
| [`app/schemas.py`](../../app/schemas.py) | `EvaluateItem`, `EvaluateRequest`, `EvaluateResultItem`, `EvaluateResponse` |
| [`data/eval/sample.jsonl`](../../data/eval/sample.jsonl) | 8-item dataset over the K8s autoscaling sample |
| [`tests/test_eval_dataset.py`](../../tests/test_eval_dataset.py) | 8 dataset-loader unit tests |
| [`tests/test_eval_runner.py`](../../tests/test_eval_runner.py) | 5 runner integration tests with real ChromaDB + fakes |
| [`tests/test_api.py`](../../tests/test_api.py) | 5 new `/evaluate` endpoint tests |
| [`tests/conftest.py`](../../tests/conftest.py) | `_FakeScorer` + `fake_scorer` fixture so tests never call RAGAS |

The architecture invariants from earlier phases still hold:

- `ragas` and `langchain_groq` imports are confined to
  `app/eval/scorer.py`.
- The API handler depends only on the `Scorer` Protocol — it never
  imports RAGAS.
- Tests use a fake scorer; the real one is only constructed in
  production code paths.

## Walkthrough: a `POST /evaluate` request

```
1. FastAPI dispatches to evaluate_endpoint (app/api/evaluate.py)
2. EvaluateRequest is validated by Pydantic
3. run_evaluation(...) is called for each item:
   3a. Run the chosen retrieval strategy (basic or improved)
   3b. Apply similarity floor; if no chunk passes, the answer is the
       safe phrase and the LLM is NOT called. The item is recorded as
       'declined'.
   3c. Otherwise: assemble_prompt + generator.generate -> answer.
4. Build a list of (question, answer, contexts, ground_truth) tuples.
5. scorer.score(items) -> RAGAS runs each active metric:
       faithfulness, answer_relevancy, context_precision, context_recall
   Each metric makes its own LLM calls behind the scenes. RAGAS
   produces one score per (item, metric) cell.
6. The runner shapes the results:
   - per-item: {metric_name -> float|None}
   - summary: {metric_name + "_avg": mean over items where the metric
     was scored}
7. Return EvaluateResponse with results, summary, item_count,
   answered_count, declined_count.
```

## API endpoint

```
POST /evaluate     body = { collection, strategy, items[], k? }
                   returns { collection, strategy, results[], summary,
                             item_count, answered_count, declined_count }
```

Full request/response shapes with examples live in
[`docs/00-design/05-api-contract.md`](../00-design/05-api-contract.md).

## How to run it

### Tests

```bash
source .venv/bin/activate
ruff check app tests
ruff format --check app tests
pytest -v
```

Expected: **80 passed**. The whole suite still finishes in under 10
seconds because the fake scorer never calls Groq.

### Real evaluation against Groq

You need a working `GROQ_API_KEY` in `.env` (the same one Phase 2 used).

```bash
source .venv/bin/activate
HF_HOME=$(pwd)/.cache/huggingface uvicorn app.main:app --reload
```

In another shell, ingest a doc and run an evaluation:

```bash
# Ingest the K8s autoscaling sample
curl -X POST http://127.0.0.1:8000/ingest \
     -F "file=@data/raw/sample.md" \
     -F "collection=k8s"

# Evaluate three questions against it
curl -X POST http://127.0.0.1:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "collection": "k8s",
    "strategy": "basic",
    "items": [
      {
        "question": "What does the Horizontal Pod Autoscaler do?",
        "ground_truth": "The HPA scales the number of pod replicas based on observed metrics like CPU."
      },
      {
        "question": "What is the capital of France?",
        "ground_truth": "I cannot answer this question from the provided documents."
      }
    ]
  }'
```

A 3-item run takes **2-4 minutes** on Groq's free tier — RAGAS
issues several LLM calls per metric per item. This is normal; it is
also why we batch and why the test suite uses the fake scorer.

To compare strategies, run the same request with
`"strategy": "basic"` and again with `"strategy": "improved"`, then
diff the `summary` objects.

You can also load the shipped 8-item dataset:

```bash
python3 - <<'PY'
import json, requests
from app.eval.dataset import load_dataset
items = [{"question": it.question, "ground_truth": it.ground_truth}
         for it in load_dataset("data/eval/sample.jsonl")]
r = requests.post("http://127.0.0.1:8000/evaluate", json={
    "collection": "k8s",
    "strategy": "basic",
    "items": items,
})
print(json.dumps(r.json()["summary"], indent=2))
PY
```

## How to read the numbers

Every RAGAS metric is in `[0.0, 1.0]`. Higher is better.

- **`faithfulness`** — does the answer follow from the retrieved
  context? `0.5` means about half the claims in the answer are not
  supported by the chunks. *This is the hallucination metric.*
- **`answer_relevancy`** — does the answer actually address the
  question? `1.0` means yes; lower means the answer drifted.
- **`context_precision`** — were the retrieved chunks actually
  useful? `1.0` means each chunk earned its slot. Low values flag
  noisy retrieval. (Needs `ground_truth`.)
- **`context_recall`** — did retrieval find everything needed for
  the ground-truth answer? Low values mean recall failure: the
  document had the answer but we did not pull it. (Needs
  `ground_truth`.)

`summary.<metric>_avg` averages over only the items that had a
score for that metric. Items missing `ground_truth` simply do not
contribute to `context_precision_avg` or `context_recall_avg`.

## A subtlety about declined items

When the system correctly declines (similarity floor short-circuit),
RAGAS sees an empty context and the safe phrase as the answer. It
cannot tell the difference between "correctly declined" and
"failed retrieval". Today it scores all context-related metrics
**0.0** for declined items and pulls down the averages.

That is a *known limitation of metric-as-judge evaluation*, not a
bug in the runner. Two ways to deal with it:

1. **Filter declines out before averaging.** Add `"include_declined":
   false` to the request (not implemented yet — see
   `alternatives.md`).
2. **Add a separate "refusal correctness" check.** A simple boolean
   per item: did the system decline iff the ground truth is the safe
   phrase? Phase 5+ candidate.

For now, *read the per-item table*, not just the summary, when
declines are present.

## Exercises

1. **A/B the strategies.** Ingest the K8s sample, run `/evaluate`
   with `strategy: "basic"` and again with `"improved"`. Compare
   `summary.context_precision_avg` and `summary.faithfulness_avg`.
   When does improved actually win? When does it tie?

2. **Detect a real hallucination.** Add a question whose ground
   truth is technically *wrong* but plausible-sounding (e.g. claim
   the HPA scales nodes). Run eval. The faithfulness score should
   stay high (the model is faithful to the *retrieved chunks*) even
   though the ground truth is wrong. Note what RAGAS *cannot*
   detect.

3. **Watch context recall fail.** Lower `top_k` in `.env` to `1`.
   Re-run. `context_recall` should drop on multi-hop questions
   (those needing several chunks).

4. **Watch faithfulness fail.** Raise the LLM temperature in
   `app/core/generation.py` (`temperature=1.0` instead of `0.0`).
   Re-run. Faithfulness should degrade on complex questions because
   the model improvises more.

5. **Score a corrupted answer.** Manually call `RagasScorer.score`
   with a hand-written wrong answer over correct contexts. Confirm
   the score drops as expected. (Why is this useful? It separates
   *retrieval* failures from *generation* failures during debugging.)

## What's next

Phase 5 closes the loop with **observability and packaging**: a
structured query log, a `/health` endpoint, a `/logs` tail
endpoint, a Dockerfile + docker-compose, CI, and the README polish
that makes the whole thing demoable.

## Further reading

- [`concepts.md`](concepts.md) — what each metric *actually*
  computes, why we use LLM-as-judge, the gold-standard alternatives
- [`alternatives.md`](alternatives.md) — RAGAS vs. custom heuristics
  vs. human eval, where to put refusal correctness, when to
  precompute eval embeddings
- [`references.md`](references.md) — RAGAS paper, classical IR
  evaluation references, "LLM-as-judge" critiques
- [`05-api-contract.md`](../00-design/05-api-contract.md) — the
  endpoint shape

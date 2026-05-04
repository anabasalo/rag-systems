"""Eval runner.

For each item: run the chosen retrieval strategy, generate an answer
(or short-circuit with the safe answer), collect (question, answer,
retrieved contexts, ground truth), then score the whole batch with
the injected ``Scorer``. Aggregate per-metric averages.

Layered: the runner orchestrates ``app.core`` retrieval and
generation. It does not import FastAPI, ChromaDB, or RAGAS directly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.config import Settings
from app.core.embedders import Embedder
from app.core.generation import Generator, assemble_prompt
from app.core.retrieval import (
    RetrievalResult,
    basic_retrieve,
    improved_retrieve,
)
from app.db.vector_store import VectorStore
from app.eval.dataset import EvalItem
from app.eval.scorer import (
    METRICS_REQUIRING_GROUND_TRUTH,
    METRICS_WITHOUT_GROUND_TRUTH,
    ScoreItem,
    Scorer,
)

NO_ANSWER = "I cannot answer this question from the provided documents."


@dataclass(frozen=True)
class EvalRunItemResult:
    question: str
    answer: str
    ground_truth: str | None
    retrieved_doc_names: list[str]
    metrics: dict[str, float | None]


@dataclass(frozen=True)
class EvalRunResult:
    strategy: str
    collection: str
    items: list[EvalRunItemResult]
    summary: dict[str, float | None]
    answered_count: int
    declined_count: int
    metric_names: list[str] = field(default_factory=list)


def _retrieve(
    *,
    strategy: str,
    question: str,
    collection: str,
    vector_store: VectorStore,
    embedder: Embedder,
    k: int,
) -> RetrievalResult:
    if strategy == "improved":
        return improved_retrieve(
            question=question,
            collection=collection,
            vector_store=vector_store,
            embedder=embedder,
            k=k,
        )
    return basic_retrieve(
        question=question,
        collection=collection,
        vector_store=vector_store,
        embedder=embedder,
        k=k,
    )


def run_evaluation(
    *,
    items: Sequence[EvalItem],
    collection: str,
    strategy: str,
    settings: Settings,
    vector_store: VectorStore,
    embedder: Embedder,
    generator: Generator,
    scorer: Scorer,
    k: int | None = None,
) -> EvalRunResult:
    """Run the full eval loop and return per-item + aggregate scores."""
    effective_k = k or settings.top_k

    score_inputs: list[ScoreItem] = []
    interim: list[dict] = []
    answered_count = 0
    declined_count = 0

    for item in items:
        retrieval = _retrieve(
            strategy=strategy,
            question=item.question,
            collection=collection,
            vector_store=vector_store,
            embedder=embedder,
            k=effective_k,
        )

        above_floor = [c for c in retrieval.chunks if c.score >= settings.similarity_floor]

        if not above_floor:
            answer = NO_ANSWER
            contexts: list[str] = []
            doc_names: list[str] = []
            declined_count += 1
        else:
            system, user = assemble_prompt(item.question, above_floor)
            gen = generator.generate(system=system, user=user)
            answer = gen.answer
            contexts = [c.text for c in above_floor]
            doc_names = [c.doc_name for c in above_floor]
            answered_count += 1

        interim.append(
            {
                "question": item.question,
                "answer": answer,
                "ground_truth": item.ground_truth,
                "retrieved_doc_names": doc_names,
            }
        )
        score_inputs.append(
            ScoreItem(
                question=item.question,
                answer=answer,
                retrieved_contexts=contexts,
                ground_truth=item.ground_truth,
            )
        )

    metric_rows = scorer.score(score_inputs)

    metric_names_set: set[str] = set()
    for row in metric_rows:
        metric_names_set.update(row.keys())
    if not metric_names_set:
        metric_names_set = set(METRICS_WITHOUT_GROUND_TRUTH + METRICS_REQUIRING_GROUND_TRUTH)
    metric_names = sorted(metric_names_set)

    item_results: list[EvalRunItemResult] = []
    for state, row in zip(interim, metric_rows, strict=False):
        normalized: dict[str, float | None] = {}
        for name in metric_names:
            value = row.get(name)
            if isinstance(value, int | float) and not math.isnan(float(value)):
                normalized[name] = float(value)
            else:
                normalized[name] = None
        item_results.append(
            EvalRunItemResult(
                question=state["question"],
                answer=state["answer"],
                ground_truth=state["ground_truth"],
                retrieved_doc_names=state["retrieved_doc_names"],
                metrics=normalized,
            )
        )

    summary = _summarize(item_results, metric_names)

    return EvalRunResult(
        strategy=strategy,
        collection=collection,
        items=item_results,
        summary=summary,
        answered_count=answered_count,
        declined_count=declined_count,
        metric_names=metric_names,
    )


def _summarize(
    items: Sequence[EvalRunItemResult],
    metric_names: Sequence[str],
) -> dict[str, float | None]:
    """Mean per metric across items where the metric was scored."""
    out: dict[str, float | None] = {}
    for name in metric_names:
        values = [it.metrics[name] for it in items if it.metrics.get(name) is not None]
        if not values:
            out[f"{name}_avg"] = None
        else:
            out[f"{name}_avg"] = sum(values) / len(values)
    return out

"""Eval scoring backed by RAGAS.

The ``Scorer`` Protocol keeps RAGAS at arm's length. Tests inject a
``_FakeScorer`` (see ``tests/conftest.py``); the real implementation
``RagasScorer`` is only constructed in production code paths.

RAGAS computes its metrics by asking an LLM to read each (question,
answer, contexts, reference) tuple and return a score. We re-use the
same Groq model that generates answers, plumbed in via langchain's
``ChatGroq`` and RAGAS' ``LangchainLLMWrapper``. For embeddings we
adapt the project's existing ``Embedder`` (no second model loaded).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.embedders import Embedder
from app.core.exceptions import LLMUnavailable


@dataclass(frozen=True)
class ScoreItem:
    """One row in the input to ``Scorer.score``."""

    question: str
    answer: str
    retrieved_contexts: list[str]
    ground_truth: str | None = None


class Scorer(Protocol):
    """Score a batch of (question, answer, contexts, ground_truth) tuples."""

    def score(self, items: Sequence[ScoreItem]) -> list[dict[str, float | None]]: ...


# RAGAS-supported metric names this project surfaces. Two of them
# require ``ground_truth``; the others do not.
METRICS_WITHOUT_GROUND_TRUTH = ("faithfulness", "answer_relevancy")
METRICS_REQUIRING_GROUND_TRUTH = ("context_precision", "context_recall")
ALL_METRICS = METRICS_WITHOUT_GROUND_TRUTH + METRICS_REQUIRING_GROUND_TRUTH


class _LangchainEmbedderAdapter:
    """Bridge from this project's ``Embedder`` to langchain's ``Embeddings``.

    RAGAS' ``LangchainEmbeddingsWrapper`` accepts any langchain
    ``Embeddings`` instance. Implementing the two methods directly here
    avoids pulling in ``langchain-huggingface`` and re-loads no model.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed([text])[0]


class RagasScorer:
    """Run RAGAS metrics on a batch using Groq + the project's embedder.

    Construction is cheap; the LLM and the wrappers are built lazily on
    the first ``score`` call so the import-time cost of langchain stays
    out of the API startup path.
    """

    def __init__(
        self,
        groq_api_key: str,
        llm_model: str,
        embedder: Embedder,
        metrics: Sequence[str] = ALL_METRICS,
    ) -> None:
        self._api_key = groq_api_key
        self._llm_model = llm_model
        self._embedder = embedder
        self._metric_names: tuple[str, ...] = tuple(metrics)
        self._llm = None
        self._embeddings_wrapper = None

    def _ensure_ready(self) -> None:
        if self._llm is not None:
            return
        if not self._api_key:
            raise LLMUnavailable("GROQ_API_KEY is not set; RAGAS needs an LLM to judge.")

        try:
            from langchain_groq import ChatGroq
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
        except ImportError as exc:  # pragma: no cover - defensive
            raise LLMUnavailable(f"RAGAS dependencies not installed: {exc}") from exc

        chat = ChatGroq(api_key=self._api_key, model=self._llm_model, temperature=0.0)
        self._llm = LangchainLLMWrapper(chat)
        self._embeddings_wrapper = LangchainEmbeddingsWrapper(
            _LangchainEmbedderAdapter(self._embedder)
        )

    def score(self, items: Sequence[ScoreItem]) -> list[dict[str, float | None]]:
        if not items:
            return []
        self._ensure_ready()

        try:
            from ragas import EvaluationDataset, evaluate
            from ragas.dataset_schema import SingleTurnSample
            from ragas.metrics import (
                answer_relevancy,
                context_precision,
                context_recall,
                faithfulness,
            )
        except ImportError as exc:  # pragma: no cover
            raise LLMUnavailable(f"RAGAS dependencies not installed: {exc}") from exc

        registry = {
            "faithfulness": faithfulness,
            "answer_relevancy": answer_relevancy,
            "context_precision": context_precision,
            "context_recall": context_recall,
        }

        # Items without ground_truth get only the metrics that don't need
        # one. To keep the batch contract simple, we run the full metric
        # set on the whole batch but mark missing-ground-truth metrics as
        # None per item before returning.
        active_metrics = [registry[name] for name in self._metric_names if name in registry]

        samples = []
        for item in items:
            samples.append(
                SingleTurnSample(
                    user_input=item.question,
                    response=item.answer,
                    retrieved_contexts=item.retrieved_contexts or [""],
                    reference=item.ground_truth or "",
                )
            )

        dataset = EvaluationDataset(samples=samples)

        try:
            result = evaluate(
                dataset=dataset,
                metrics=active_metrics,
                llm=self._llm,
                embeddings=self._embeddings_wrapper,
                show_progress=False,
                raise_exceptions=False,
            )
        except Exception as exc:  # noqa: BLE001 - vendor surface
            raise LLMUnavailable(f"RAGAS evaluation failed: {exc}") from exc

        # ``result`` exposes ``.scores`` -- a list of dicts per item.
        per_item: list[dict[str, float | None]] = []
        for i, item in enumerate(items):
            row = result.scores[i] if i < len(result.scores) else {}
            scores: dict[str, float | None] = {}
            for name in self._metric_names:
                if item.ground_truth is None and name in METRICS_REQUIRING_GROUND_TRUTH:
                    scores[name] = None
                    continue
                value = row.get(name)
                scores[name] = float(value) if isinstance(value, int | float) else None
            per_item.append(scores)
        return per_item

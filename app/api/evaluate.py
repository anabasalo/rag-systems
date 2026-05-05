"""HTTP handler for /evaluate.

Runs a chosen retrieval strategy on each input question, generates an
answer (or short-circuits with the safe answer below the similarity
floor), then scores the batch with the injected ``Scorer``. Returns
per-item metrics and the aggregate summary.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_embedder,
    get_generator,
    get_query_logger,
    get_scorer,
    get_settings_dep,
    get_vector_store,
)
from app.config import Settings
from app.core.embedders import Embedder
from app.core.generation import Generator
from app.db.vector_store import VectorStore
from app.eval.dataset import EvalItem
from app.eval.runner import run_evaluation
from app.eval.scorer import Scorer
from app.observability.query_log import QueryLogger
from app.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    EvaluateResultItem,
)

router = APIRouter(tags=["evaluate"])


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate_endpoint(
    body: EvaluateRequest,
    settings: Settings = Depends(get_settings_dep),
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
    scorer: Scorer = Depends(get_scorer),
    query_logger: QueryLogger = Depends(get_query_logger),
) -> EvaluateResponse:
    eval_items = [
        EvalItem(question=item.question, ground_truth=item.ground_truth) for item in body.items
    ]

    started = time.perf_counter()
    run = run_evaluation(
        items=eval_items,
        collection=body.collection,
        strategy=body.strategy,
        settings=settings,
        vector_store=vector_store,
        embedder=embedder,
        generator=generator,
        scorer=scorer,
        k=body.k,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    query_logger.record(
        endpoint="/evaluate",
        status="ok",
        collection=body.collection,
        strategy=body.strategy,
        question=None,
        n_sources=None,
        latency_ms=latency_ms,
        tokens=None,
        extra={
            "item_count": len(run.items),
            "answered_count": run.answered_count,
            "declined_count": run.declined_count,
            "summary": run.summary,
        },
    )

    return EvaluateResponse(
        collection=run.collection,
        strategy=run.strategy,
        results=[
            EvaluateResultItem(
                question=item.question,
                answer=item.answer,
                ground_truth=item.ground_truth,
                retrieved_doc_names=item.retrieved_doc_names,
                metrics=item.metrics,
            )
            for item in run.items
        ],
        summary=run.summary,
        item_count=len(run.items),
        answered_count=run.answered_count,
        declined_count=run.declined_count,
    )

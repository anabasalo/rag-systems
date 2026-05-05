"""HTTP handlers for /query and /compare.

The control flow for a single strategy is:

1. Validate request via Pydantic.
2. Run retrieval (``basic`` or ``improved``), with optional ``doc_filter``.
3. If no chunk passes the similarity floor, short-circuit with the
   "I cannot answer" response. The LLM is NOT called in this case.
4. Otherwise, assemble the prompt and call the generator.
5. Return answer + sources + latency + token usage.

``/compare`` runs steps 2-5 twice (once per strategy) and returns both.

Layered: this handler does not import ChromaDB or call Groq directly.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_embedder,
    get_generator,
    get_query_logger,
    get_settings_dep,
    get_vector_store,
)
from app.config import Settings
from app.core.embedders import Embedder
from app.core.generation import Generator, assemble_prompt
from app.core.retrieval import (
    RetrievalResult,
    basic_retrieve,
    improved_retrieve,
)
from app.db.vector_store import VectorStore
from app.observability.query_log import QueryLogger
from app.schemas import (
    CompareRequest,
    CompareResponse,
    QueryRequest,
    QueryResponse,
    SourceChunk,
    StrategyResult,
    TokenUsage,
)

router = APIRouter(tags=["query"])

NO_ANSWER = "I cannot answer this question from the provided documents."


def _retrieve(
    *,
    strategy: str,
    question: str,
    collection: str,
    vector_store: VectorStore,
    embedder: Embedder,
    k: int,
    doc_filter: dict | None,
) -> RetrievalResult:
    if strategy == "improved":
        return improved_retrieve(
            question=question,
            collection=collection,
            vector_store=vector_store,
            embedder=embedder,
            k=k,
            doc_filter=doc_filter,
        )
    return basic_retrieve(
        question=question,
        collection=collection,
        vector_store=vector_store,
        embedder=embedder,
        k=k,
        doc_filter=doc_filter,
    )


def _run_strategy(
    *,
    strategy: str,
    question: str,
    collection: str,
    vector_store: VectorStore,
    embedder: Embedder,
    generator: Generator,
    settings: Settings,
    k: int,
    doc_filter: dict | None,
) -> tuple[str, list[SourceChunk], int, TokenUsage | None, str]:
    """Run one strategy end-to-end. Returns (answer, sources, latency_ms, tokens, strategy_name)."""
    started = time.perf_counter()

    retrieval = _retrieve(
        strategy=strategy,
        question=question,
        collection=collection,
        vector_store=vector_store,
        embedder=embedder,
        k=k,
        doc_filter=doc_filter,
    )

    above_floor = [c for c in retrieval.chunks if c.score >= settings.similarity_floor]

    if not above_floor:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return NO_ANSWER, [], latency_ms, None, retrieval.strategy

    system, user = assemble_prompt(question, above_floor)
    gen = generator.generate(system=system, user=user)

    latency_ms = int((time.perf_counter() - started) * 1000)
    sources = [
        SourceChunk(
            chunk_id=c.chunk_id,
            doc_name=c.doc_name,
            chunk_index=c.chunk_index,
            score=c.score,
            text=c.text,
        )
        for c in above_floor
    ]
    tokens = TokenUsage(prompt=gen.prompt_tokens, completion=gen.completion_tokens)
    return gen.answer, sources, latency_ms, tokens, retrieval.strategy


@router.post("/query", response_model=QueryResponse)
def query_endpoint(
    body: QueryRequest,
    settings: Settings = Depends(get_settings_dep),
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
    query_logger: QueryLogger = Depends(get_query_logger),
) -> QueryResponse:
    k = body.k or settings.top_k
    doc_filter = body.doc_filter.model_dump(exclude_none=True) if body.doc_filter else None

    answer, sources, latency_ms, tokens, strategy_name = _run_strategy(
        strategy=body.strategy,
        question=body.question,
        collection=body.collection,
        vector_store=vector_store,
        embedder=embedder,
        generator=generator,
        settings=settings,
        k=k,
        doc_filter=doc_filter,
    )

    query_logger.record(
        endpoint="/query",
        status="declined" if not sources else "ok",
        collection=body.collection,
        strategy=strategy_name,
        question=body.question,
        n_sources=len(sources),
        latency_ms=latency_ms,
        tokens=tokens.model_dump() if tokens else None,
    )

    return QueryResponse(
        answer=answer,
        collection=body.collection,
        strategy=strategy_name,
        sources=sources,
        latency_ms=latency_ms,
        tokens=tokens,
    )


@router.post("/compare", response_model=CompareResponse)
def compare_endpoint(
    body: CompareRequest,
    settings: Settings = Depends(get_settings_dep),
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
    query_logger: QueryLogger = Depends(get_query_logger),
) -> CompareResponse:
    """Run ``basic`` and ``improved`` on the same question; return both."""
    k = body.k or settings.top_k
    doc_filter = body.doc_filter.model_dump(exclude_none=True) if body.doc_filter else None

    basic_answer, basic_sources, basic_latency, basic_tokens, basic_name = _run_strategy(
        strategy="basic",
        question=body.question,
        collection=body.collection,
        vector_store=vector_store,
        embedder=embedder,
        generator=generator,
        settings=settings,
        k=k,
        doc_filter=doc_filter,
    )

    improved_answer, improved_sources, improved_latency, improved_tokens, improved_name = (
        _run_strategy(
            strategy="improved",
            question=body.question,
            collection=body.collection,
            vector_store=vector_store,
            embedder=embedder,
            generator=generator,
            settings=settings,
            k=k,
            doc_filter=doc_filter,
        )
    )

    query_logger.record(
        endpoint="/compare",
        status="ok",
        collection=body.collection,
        strategy="basic+improved",
        question=body.question,
        n_sources=len(basic_sources) + len(improved_sources),
        latency_ms=basic_latency + improved_latency,
        tokens=None,
        extra={
            "basic": {
                "n_sources": len(basic_sources),
                "latency_ms": basic_latency,
                "tokens": basic_tokens.model_dump() if basic_tokens else None,
            },
            "improved": {
                "n_sources": len(improved_sources),
                "latency_ms": improved_latency,
                "tokens": improved_tokens.model_dump() if improved_tokens else None,
            },
        },
    )

    return CompareResponse(
        question=body.question,
        collection=body.collection,
        basic=StrategyResult(
            answer=basic_answer,
            strategy=basic_name,
            sources=basic_sources,
            latency_ms=basic_latency,
            tokens=basic_tokens,
        ),
        improved=StrategyResult(
            answer=improved_answer,
            strategy=improved_name,
            sources=improved_sources,
            latency_ms=improved_latency,
            tokens=improved_tokens,
        ),
    )

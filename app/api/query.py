"""HTTP handler for /query.

The control flow:

1. Validate request via Pydantic.
2. Run retrieval (basic vector cosine top-K, with optional doc_filter).
3. If no chunk passes the similarity floor, short-circuit with the
   "I cannot answer" response. The LLM is NOT called in this case.
4. Otherwise, assemble the prompt and call the generator.
5. Return answer + sources + latency + token usage.

Layered: this handler does not import ChromaDB or call Groq directly.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_embedder,
    get_generator,
    get_settings_dep,
    get_vector_store,
)
from app.config import Settings
from app.core.embedders import Embedder
from app.core.generation import Generator, assemble_prompt
from app.core.retrieval import basic_retrieve
from app.db.vector_store import VectorStore
from app.schemas import QueryRequest, QueryResponse, SourceChunk, TokenUsage

router = APIRouter(tags=["query"])

NO_ANSWER = "I cannot answer this question from the provided documents."


@router.post("/query", response_model=QueryResponse)
def query_endpoint(
    body: QueryRequest,
    settings: Settings = Depends(get_settings_dep),
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
) -> QueryResponse:
    started = time.perf_counter()

    k = body.k or settings.top_k
    doc_filter = body.doc_filter.model_dump(exclude_none=True) if body.doc_filter else None

    retrieval = basic_retrieve(
        question=body.question,
        collection=body.collection,
        vector_store=vector_store,
        embedder=embedder,
        k=k,
        doc_filter=doc_filter,
    )

    above_floor = [c for c in retrieval.chunks if c.score >= settings.similarity_floor]

    if not above_floor:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return QueryResponse(
            answer=NO_ANSWER,
            collection=body.collection,
            strategy=retrieval.strategy,
            sources=[],
            latency_ms=latency_ms,
            tokens=None,
        )

    system, user = assemble_prompt(body.question, above_floor)
    gen = generator.generate(system=system, user=user)

    latency_ms = int((time.perf_counter() - started) * 1000)

    return QueryResponse(
        answer=gen.answer,
        collection=body.collection,
        strategy=retrieval.strategy,
        sources=[
            SourceChunk(
                chunk_id=c.chunk_id,
                doc_name=c.doc_name,
                chunk_index=c.chunk_index,
                score=c.score,
                text=c.text,
            )
            for c in above_floor
        ],
        latency_ms=latency_ms,
        tokens=TokenUsage(prompt=gen.prompt_tokens, completion=gen.completion_tokens),
    )

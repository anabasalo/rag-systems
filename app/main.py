"""FastAPI application factory and exception handlers.

Run locally:

    uvicorn app.main:app --reload

Exception handlers map ``app.core.exceptions`` (and ``IngestionError``)
to the HTTP status codes documented in
``docs/00-design/05-api-contract.md``. Layers below ``api/`` never
raise FastAPI's ``HTTPException`` directly.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api import evaluate as evaluate_api
from app.api import health as health_api
from app.api import ingest as ingest_api
from app.api import logs as logs_api
from app.api import query as query_api
from app.core.exceptions import CollectionNotFound, DocumentNotFound, LLMUnavailable
from app.core.ingestion import IngestionError


def create_app() -> FastAPI:
    app = FastAPI(
        title="rag-systems",
        version=__version__,
        description=(
            "Production-shaped RAG service. See docs/00-design/05-api-contract.md "
            "for the full contract."
        ),
    )

    app.include_router(ingest_api.router)
    app.include_router(query_api.router)
    app.include_router(evaluate_api.router)
    app.include_router(health_api.router)
    app.include_router(logs_api.router)

    @app.exception_handler(CollectionNotFound)
    async def _collection_404(_request: Request, exc: CollectionNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "CollectionNotFound",
                "message": str(exc),
                "details": {"collection": exc.name},
            },
        )

    @app.exception_handler(DocumentNotFound)
    async def _document_404(_request: Request, exc: DocumentNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={
                "error": "DocumentNotFound",
                "message": str(exc),
                "details": {
                    "collection": exc.collection,
                    "doc_name": exc.doc_name,
                },
            },
        )

    @app.exception_handler(IngestionError)
    async def _ingestion_422(_request: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": "IngestionError",
                "message": str(exc),
                "details": {},
            },
        )

    @app.exception_handler(LLMUnavailable)
    async def _llm_502(_request: Request, exc: LLMUnavailable) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={
                "error": "LLMUnavailable",
                "message": str(exc),
                "details": {},
            },
        )

    return app


app = create_app()

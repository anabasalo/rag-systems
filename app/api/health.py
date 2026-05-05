"""Liveness check.

Returns version + a cheap signal that the process can talk to its
storage layer (counting collections is a one-shot SQLite read).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_vector_store
from app.db.vector_store import VectorStore
from app.schemas import HealthResponse

router = APIRouter(tags=["ops"])


@router.get("/health", response_model=HealthResponse)
def health_endpoint(
    vector_store: VectorStore = Depends(get_vector_store),
) -> HealthResponse:
    try:
        collections = len(vector_store.list_collections())
    except Exception:  # noqa: BLE001 - the endpoint must always answer
        collections = 0
    return HealthResponse(
        status="ok",
        version=__version__,
        collections=collections,
    )

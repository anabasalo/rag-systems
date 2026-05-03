"""HTTP handlers for ingestion and collection management.

Endpoints:
    POST   /ingest
    GET    /collections
    GET    /collections/{name}/docs
    DELETE /collections/{name}/docs/{doc_name}
    DELETE /collections/{name}
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_embedder, get_vector_store
from app.core.embedders import Embedder
from app.core.exceptions import CollectionNotFound, DocumentNotFound
from app.core.ingestion import ingest as ingest_document
from app.db.vector_store import VectorStore
from app.schemas import (
    COLLECTION_NAME_PATTERN,
    CollectionInfo,
    CollectionListResponse,
    DocInfo,
    DocListResponse,
    IngestResponse,
)

router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_endpoint(
    file: UploadFile = File(...),
    collection: str = Form(..., pattern=COLLECTION_NAME_PATTERN),
    tags: str = Form(""),
    vector_store: VectorStore = Depends(get_vector_store),
    embedder: Embedder = Depends(get_embedder),
) -> IngestResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename is required")

    safe_name = Path(file.filename).name  # strip any path traversal

    # Stage the upload to a temp directory using the original filename so the
    # ingestion pipeline records the right `doc_name` (extension included).
    with tempfile.TemporaryDirectory() as tmp_dir:
        staged_path = Path(tmp_dir) / safe_name
        with staged_path.open("wb") as out_fp:
            shutil.copyfileobj(file.file, out_fp)

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        result = ingest_document(
            file_path=staged_path,
            collection=collection,
            vector_store=vector_store,
            embedder=embedder,
            tags=tag_list,
        )

    return IngestResponse(
        doc_id=result.doc_id,
        doc_name=result.doc_name,
        collection=result.collection,
        chunks_written=result.chunks_written,
        uploaded_at=result.uploaded_at,
    )


@router.get("/collections", response_model=CollectionListResponse)
def list_collections_endpoint(
    vector_store: VectorStore = Depends(get_vector_store),
) -> CollectionListResponse:
    summaries = vector_store.list_collections()
    return CollectionListResponse(
        collections=[
            CollectionInfo(name=s.name, doc_count=s.doc_count, chunk_count=s.chunk_count)
            for s in summaries
        ]
    )


@router.get("/collections/{name}/docs", response_model=DocListResponse)
def list_docs_endpoint(
    name: str,
    vector_store: VectorStore = Depends(get_vector_store),
) -> DocListResponse:
    if not vector_store.collection_exists(name):
        raise CollectionNotFound(name)
    docs = vector_store.list_docs(name)
    return DocListResponse(
        collection=name,
        docs=[
            DocInfo(doc_name=d.doc_name, chunks=d.chunks, uploaded_at=d.uploaded_at) for d in docs
        ],
    )


@router.delete(
    "/collections/{name}/docs/{doc_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_doc_endpoint(
    name: str,
    doc_name: str,
    vector_store: VectorStore = Depends(get_vector_store),
) -> None:
    if not vector_store.collection_exists(name):
        raise CollectionNotFound(name)
    removed = vector_store.delete_doc(name, doc_name)
    if removed == 0:
        raise DocumentNotFound(name, doc_name)


@router.delete("/collections/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_collection_endpoint(
    name: str,
    vector_store: VectorStore = Depends(get_vector_store),
) -> None:
    if not vector_store.collection_exists(name):
        raise CollectionNotFound(name)
    vector_store.delete_collection(name)

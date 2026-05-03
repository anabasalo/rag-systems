"""Document ingestion: parse a file, split into chunks, embed, persist.

This module is the only place the chunking strategy and metadata schema
live. The vector store and the embedder are passed in so this is unit
testable without a real ChromaDB or a real sentence-transformers model.

Metadata schema is defined in `docs/00-design/04-data-model.md`.
Chunking decisions are recorded in ADR 0004.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.embedders import Embedder

SUPPORTED_EXTENSIONS = {".pdf", ".md", ".markdown", ".txt"}


class IngestionError(Exception):
    """Raised when a document cannot be parsed or chunked."""


@dataclass(frozen=True)
class IngestionResult:
    doc_id: str
    doc_name: str
    collection: str
    chunks_written: int
    uploaded_at: str
    source_type: str


def ingest(
    file_path: Path | str,
    collection: str,
    vector_store,
    embedder: Embedder,
    tags: Iterable[str] | None = None,
    chunk_size: int = 2000,
    chunk_overlap: int = 200,
) -> IngestionResult:
    """Ingest one file into one collection.

    The flow is:
    1. parse the file to plain text (PDF / MD / TXT)
    2. split into overlapping chunks
    3. delete any existing chunks for this `doc_name` (idempotent re-ingest)
    4. embed the chunks
    5. write chunks + metadata to the vector store
    """
    path = Path(file_path)
    if not path.exists():
        raise IngestionError(f"File not found: {path}")

    source_type = _infer_source_type(path)
    text = _parse_file(path, source_type)
    chunks = chunk_text(text, target_size=chunk_size, overlap=chunk_overlap)

    if not chunks:
        raise IngestionError(f"No content extracted from: {path}")

    doc_id = str(uuid.uuid4())
    doc_name = path.name
    uploaded_at = datetime.now(UTC).isoformat()
    tags_csv = ",".join(t.strip() for t in (tags or []) if t.strip())

    metadatas: list[dict] = [
        {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "chunk_index": i,
            "tags": tags_csv,
            "uploaded_at": uploaded_at,
            "source_type": source_type,
        }
        for i in range(len(chunks))
    ]

    ids = [f"{doc_id}:{i}" for i in range(len(chunks))]

    # Idempotent re-ingest: an upload of the same doc_name replaces the previous
    # version's chunks. See FR-1.4 in `docs/00-design/02-requirements.md`.
    vector_store.delete_doc(collection, doc_name)

    embeddings = embedder.embed(chunks)

    vector_store.add_chunks(
        collection=collection,
        ids=ids,
        chunks=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return IngestionResult(
        doc_id=doc_id,
        doc_name=doc_name,
        collection=collection,
        chunks_written=len(chunks),
        uploaded_at=uploaded_at,
        source_type=source_type,
    )


def chunk_text(text: str, target_size: int = 2000, overlap: int = 200) -> list[str]:
    """Split `text` into overlapping chunks of ~`target_size` characters.

    Within ±10 percent of the target size we look for, in priority order, a
    paragraph break, a sentence end, or a newline, and snap the split there.
    If none is available, we fall back to a hard character split.

    Empty / whitespace-only input yields an empty list.
    """
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= target_size:
        raise ValueError("overlap must be smaller than target_size")

    text = (text or "").strip()
    if not text:
        return []

    n = len(text)
    if n <= target_size:
        return [text]

    chunks: list[str] = []
    start = 0
    backoff = max(1, target_size // 10)

    while start < n:
        end = start + target_size
        if end >= n:
            tail = text[start:].strip()
            if tail:
                chunks.append(tail)
            break

        window_lo = max(start + 1, end - backoff)
        window_hi = min(n, end + backoff)

        boundary = -1
        para = text.rfind("\n\n", window_lo, window_hi)
        if para > start:
            boundary = min(para + 2, n)
        else:
            sentence = text.rfind(". ", window_lo, window_hi)
            if sentence > start:
                boundary = min(sentence + 2, n)
            else:
                newline = text.rfind("\n", window_lo, window_hi)
                if newline > start:
                    boundary = min(newline + 1, n)

        if boundary != -1 and boundary > start:
            end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _infer_source_type(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext == ".txt":
        return "text"
    raise IngestionError(
        f"Unsupported file extension: '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
    )


def _parse_file(path: Path, source_type: str) -> str:
    if source_type == "pdf":
        return _parse_pdf(path)
    return path.read_text(encoding="utf-8")


def _parse_pdf(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:
        raise IngestionError(
            "pdfplumber is required for PDF parsing. Install via `pip install pdfplumber`."
        ) from exc

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            pages.append(page_text)

    return "\n\n".join(pages).strip()

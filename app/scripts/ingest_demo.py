"""Ingest a single document for Phase 1 verification.

Usage::

    python -m app.scripts.ingest_demo
    python -m app.scripts.ingest_demo --file data/raw/sample.md --collection demo

The first run downloads the sentence-transformers model (about 80 MB). Later
runs hit the local cache. ChromaDB is persisted under `data/chroma/`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings
from app.core.embedders import SentenceTransformerEmbedder
from app.core.ingestion import ingest
from app.db.vector_store import VectorStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a document into a collection.")
    parser.add_argument("--file", default="data/raw/sample.md", help="Path to the file to ingest.")
    parser.add_argument("--collection", default="demo", help="Target collection name.")
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags to attach to every chunk.",
    )
    args = parser.parse_args()

    settings = get_settings()
    print(f"[config] embed_model      = {settings.embed_model}")
    print(f"[config] chroma_persist_dir = {settings.chroma_persist_dir}")
    print(f"[config] chunk_size       = {settings.chunk_size}")
    print(f"[config] chunk_overlap    = {settings.chunk_overlap}")

    embedder = SentenceTransformerEmbedder(settings.embed_model)
    store = VectorStore(persist_dir=settings.chroma_persist_dir)

    file_path = Path(args.file)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    print(f"\n[ingest] {file_path} -> collection '{args.collection}' (tags={tags or '-'})")
    result = ingest(
        file_path=file_path,
        collection=args.collection,
        vector_store=store,
        embedder=embedder,
        tags=tags,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    print(f"  doc_id          = {result.doc_id}")
    print(f"  doc_name        = {result.doc_name}")
    print(f"  source_type     = {result.source_type}")
    print(f"  chunks_written  = {result.chunks_written}")
    print(f"  uploaded_at     = {result.uploaded_at}")

    docs = store.list_docs(args.collection)
    print(f"\n[state] collection '{args.collection}' contains {len(docs)} doc(s):")
    for d in docs:
        print(f"  - {d.doc_name:30s}  chunks={d.chunks:3d}  uploaded_at={d.uploaded_at}")

    # A tiny smoke-test of retrieval against a generic query, to prove
    # writes are reachable. Uses the real embedder.
    query = "scaling and capacity"
    print(f"\n[smoke] top-3 for query: {query!r}")
    embedding = embedder.embed([query])[0]
    hits = store.query(args.collection, embedding=embedding, k=3)
    if not hits:
        print("  (no results)")
    for h in hits:
        preview = h.text.replace("\n", " ")[:80]
        print(f"  score={h.score:+.3f}  {h.doc_name}#chunk{h.chunk_index}: {preview}")


if __name__ == "__main__":
    main()

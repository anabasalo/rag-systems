"""Bulk-ingest every supported file in a directory into one collection.

Usage::

    python -m app.scripts.ingest_dir --dir data/raw --collection demo
    python -m app.scripts.ingest_dir --dir data/raw/k8s --collection k8s --tags scaling

Supported extensions are inferred from ``app.core.ingestion`` (PDF,
Markdown, plain text). The script is idempotent: re-ingesting the same
directory replaces any existing chunks for each ``doc_name``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.core.embedders import SentenceTransformerEmbedder
from app.core.ingestion import IngestionError, ingest
from app.db.vector_store import VectorStore

SUPPORTED_EXTS = {".md", ".markdown", ".txt", ".pdf"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a directory of docs into a collection.")
    parser.add_argument("--dir", required=True, help="Directory containing docs to ingest.")
    parser.add_argument("--collection", required=True, help="Target collection name.")
    parser.add_argument(
        "--tags",
        default="",
        help="Comma-separated tags applied to every chunk of every doc.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories.",
    )
    args = parser.parse_args()

    src = Path(args.dir)
    if not src.exists() or not src.is_dir():
        print(f"[error] {src} is not a directory", file=sys.stderr)
        return 2

    files = sorted(src.rglob("*") if args.recursive else src.iterdir())
    files = [p for p in files if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]

    if not files:
        print(f"[error] no supported files (*.md, *.txt, *.pdf) under {src}", file=sys.stderr)
        return 2

    settings = get_settings()
    embedder = SentenceTransformerEmbedder(settings.embed_model)
    store = VectorStore(persist_dir=settings.chroma_persist_dir)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    total_files = 0
    total_chunks = 0
    failed = 0

    print(f"[ingest] {len(files)} file(s) -> collection '{args.collection}' (tags={tags or '-'})")
    for path in files:
        try:
            result = ingest(
                file_path=path,
                collection=args.collection,
                tags=tags,
                embedder=embedder,
                vector_store=store,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )
        except IngestionError as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)
            failed += 1
            continue
        total_files += 1
        total_chunks += result.chunks_written
        print(f"  + {result.doc_name:40s} chunks={result.chunks_written:3d}")

    print()
    print(f"[done] ingested {total_files} file(s), {total_chunks} chunks")
    if failed:
        print(f"[done] {failed} file(s) failed", file=sys.stderr)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
